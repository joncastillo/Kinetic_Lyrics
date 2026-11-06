// Settings > Appearance: the backdrop and the panel colour behind each theme. Both live in the hidden "appearance"
// field of the form, so the active profile keeps them like every other setting; studio-boot.js restores them before
// paint. Built-in pictures come from frontend/art, added ones are kept in the studio output folder.
(() => {
  const A = window.studioAppearance;
  const input = document.getElementById('appearance');
  const groups = { light: document.getElementById('backdropDay'), dark: document.getElementById('backdropNight') };
  const colours = { light: document.getElementById('panelDay'), dark: document.getElementById('panelNight') };
  const resets = { light: document.getElementById('panelDayReset'), dark: document.getElementById('panelNightReset') };
  const addButton = document.getElementById('backdropAdd'), fileInput = document.getElementById('backdropFile');
  const gallery = document.getElementById('backdropGallery'), galleryPicks = document.getElementById('backdropGalleryPicks');
  const galleryTitle = document.getElementById('backdropGalleryTitle');
  const layersBox = document.getElementById('sceneLayers');
  const subtitle = document.querySelector('.section[data-section=appearance] .section-sub');
  const DEFAULT_PANEL = { light: '#0a1a3e', dark: '#26180f' };
  if (!A || !input || !groups.light || !groups.dark) return;

  let pictures = [], galleryTheme = null;
  const current = () => { try { const v = JSON.parse(input.value || '{}'); return v && typeof v === 'object' ? v : {}; } catch { return {}; } };
  const choice = (state, theme) => state[theme] || {};
  const selectedOf = (state, theme) => {
    const saved = choice(state, theme);
    const urls = Array.isArray(saved.backdrops) ? saved.backdrops : Array.isArray(saved.backdrop) ? saved.backdrop
      : [typeof saved.backdrop === 'string' ? saved.backdrop : A.DEFAULT_BACKDROP[theme]];
    return [...new Set(urls.filter(v => typeof v === 'string'))];
  };
  const backdropOf = (state, theme) => {
    const selected = selectedOf(state, theme), active = theme === A.theme() ? A.activeBackdrop?.() : null;
    return selected.includes(active) ? active : (selected[0] || '');
  };
  const nameOf = url => url ? (pictures.find(p => p.url === url)?.name || 'Picture') : 'Plain';

  // Writing the field and announcing the change is what saves it in the profile (studio-profiles.js listens).
  function commit(theme, patch) {
    const state = current(), next = { ...choice(state, theme), ...patch };
    for (const key of Object.keys(next)) if (next[key] === undefined) delete next[key];
    state[theme] = next; input.value = JSON.stringify(state);
    input.dispatchEvent(new Event('change', { bubbles: true }));
    sync();
  }
  function sync() { const state = current(); A.apply(state); render(state); }
  window.syncAppearance = sync;

  function render(state) {
    for (const [theme, box] of Object.entries(groups)) {
      box.replaceChildren();
      const chosen = backdropOf(state, theme);
      const picture = pictures.find(p => p.url === chosen);
      const pick = document.createElement('button'); pick.type = 'button'; pick.className = 'backdrop-pick backdrop-current';
      pick.setAttribute('aria-haspopup', 'dialog'); pick.setAttribute('aria-controls', 'backdropGallery');
      pick.setAttribute('aria-label', `Change ${theme === 'light' ? 'day' : 'night'} backdrop: ${nameOf(chosen)}`);
      if (chosen) pick.style.backgroundImage = `url(${picture?.poster || chosen.replace(/\.scene\.json$|\.mp4$/i, '.webp')})`;
      const caption = document.createElement('span'); caption.className = 'backdrop-current-caption';
      const count = selectedOf(state, theme).length;
      caption.textContent = nameOf(chosen) + (count > 1 ? ` · ${count} selected` : '') + ' · Change…'; pick.append(caption);
      pick.addEventListener('click', () => openGallery(theme)); box.append(pick);
      if (colours[theme] && document.activeElement !== colours[theme]) colours[theme].value = choice(state, theme).panel || DEFAULT_PANEL[theme];
      if (resets[theme]) resets[theme].disabled = !choice(state, theme).panel;
    }
    if (gallery?.open) renderGallery(state);
    if (subtitle) subtitle.textContent = nameOf(backdropOf(state, A.theme()));
    renderLayers(state);
  }

  function openGallery(theme) {
    if (!gallery || !galleryPicks) return;
    galleryTheme = theme;
    galleryTitle.textContent = `Choose ${theme === 'light' ? 'day' : 'night'} backdrop`;
    renderGallery(current()); gallery.showModal();
    galleryPicks.querySelector('input:checked')?.focus();
  }

  function renderGallery(state) {
    galleryPicks.replaceChildren();
    const theme = galleryTheme, selected = selectedOf(state, theme);
    const order = pictures.slice().sort((a, b) => (b.theme === theme) - (a.theme === theme));
    for (const picture of [{ url: '', name: 'Plain', builtin: true }, ...order]) {
      const item = document.createElement('span'); item.className = 'backdrop-item';
      const option = document.createElement('label'); option.className = 'backdrop-option'; option.title = picture.name;
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = picture.url;
      checkbox.checked = selected.includes(picture.url); checkbox.setAttribute('aria-label', picture.name);
      const pick = document.createElement('span'), on = checkbox.checked;
      pick.className = 'backdrop-pick' + (on ? ' on' : '') + (picture.url ? '' : ' plain');
      if (picture.url) pick.style.backgroundImage = `url(${picture.poster || picture.url})`; else pick.textContent = 'Plain';
      if (picture.video) { const badge = document.createElement('span'); badge.className = 'backdrop-video-badge'; badge.textContent = '▶ Video'; pick.append(badge); }
      checkbox.addEventListener('change', () => {
        const urls = selectedOf(current(), theme);
        const next = checkbox.checked ? [...new Set([...urls, picture.url])] : urls.filter(url => url !== picture.url);
        commit(theme, { backdrops: next, backdrop: next[0] || '' });
        [...galleryPicks.querySelectorAll('input')].find(el => el.value === picture.url)?.focus();
      });
      option.append(checkbox, pick); item.append(option);
      if (!picture.builtin) {
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'backdrop-remove';
        remove.textContent = '\u00d7'; remove.title = 'Remove this backdrop'; remove.setAttribute('aria-label', 'Remove this backdrop');
        remove.addEventListener('click', event => { event.stopPropagation(); drop(picture.url); });
        item.append(remove);
      }
      galleryPicks.append(item);
    }
  }

  function renderLayers(){}

  async function load() {
    try { pictures = (await api('/api/backdrops')).pictures || []; } catch { pictures = []; }
    // Choices made before they lived in the profile move over once.
    try {
      const legacy = JSON.parse(localStorage.getItem('lyricStudioBackdrops') || 'null');
      if (legacy && input.value.trim() in { '': 1, '{}': 1 }) {
        const state = {};
        for (const theme of ['light', 'dark']) {
          if (Array.isArray(legacy[theme])) {
            const urls = legacy[theme].filter(v => typeof v === 'string');
            state[theme] = {backdrops:urls, backdrop:urls[0] || ''};
          } else if (typeof legacy[theme] === 'string') state[theme] = {backdrop:legacy[theme]};
        }
        input.value = JSON.stringify(state); input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      localStorage.removeItem('lyricStudioBackdrops');
    } catch {}
    sync();
  }
  async function drop(url) {
    try { pictures = (await api('/api/backdrops/remove', { url })).pictures || []; } catch (error) { toast(error.message); return; }
    const state = current();
    for (const theme of ['light', 'dark']) {
      const urls = selectedOf(state, theme);
      if (!urls.includes(url)) continue;
      const next = urls.filter(item => item !== url);
      commit(theme, {backdrops:next.length ? next : undefined, backdrop:next.length ? next[0] : undefined});
    }
    sync();
  }
  async function add(files, theme = A.theme(), append = true) {
    const batch = Array.isArray(files) ? files : [files], added = [];
    addButton.disabled = true;
    for (const [index, file] of batch.entries()) {
      addButton.textContent = `Adding ${index+1}/${batch.length}…`;
      const data = new FormData(); data.append('picture', file, file.name);
      try {
        const result = await api('/api/backdrops', data, 120000);
        pictures = result.pictures || []; added.push(result.added);
      } catch (error) { toast(`${file.name}: ${error.message}`); }
    }
    if (added.length) {
      const urls = [...new Set([...(append ? selectedOf(current(), theme) : []), ...added])];
      commit(theme, {backdrops:urls, backdrop:urls[0]});
    }
    addButton.disabled = false; addButton.textContent = 'Add pictures or MP4s';
  }

  addButton?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', () => { const files = [...(fileInput.files || [])]; fileInput.value = ''; if (files.length) add(files, galleryTheme || A.theme()); });
  document.getElementById('closeBackdropGallery')?.addEventListener('click', () => gallery.close());
  gallery?.addEventListener('close', () => { groups[galleryTheme]?.querySelector('button')?.focus(); galleryTheme = null; });
  gallery?.addEventListener('click', event => {
    if (event.target !== gallery) return;
    const r = gallery.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) gallery.close();
  });
  for (const theme of ['light', 'dark']) {
    colours[theme]?.addEventListener('input', () => commit(theme, { panel: colours[theme].value }));
    resets[theme]?.addEventListener('click', () => commit(theme, { panel: undefined }));
  }
  // The theme switch and the system scheme both change which choice shows.
  new MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  matchMedia('(prefers-color-scheme:light)').addEventListener('change', sync);
  document.addEventListener('studio-scene-ready', () => render(current()));
  document.addEventListener('studio-backdrop-change', () => render(current()));
  load();
  window.addStudioBackdrop = async file => { await add(file, A.theme(), false); };
  window.chooseStudioBackdrop = url => commit(A.theme(), {backdrop:url, backdrops:undefined});
})();
