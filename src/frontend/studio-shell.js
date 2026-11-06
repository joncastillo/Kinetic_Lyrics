// Studio shell: workspace tabs, the settings drawer with its step bar, settings search, collapsible sections,
// the theme switch and the gallery's empty notices. It only reads the page the other modules build.
(() => {
  const $ = id => document.getElementById(id);
  const workspace = document.querySelector('.workspace');
  // inline state only: the tab stylesheet hides panels on other tabs, which must not count as 'gone'
  const visible = el => el && !el.hidden && el.style.display !== 'none';

  // ---- tabs: Home while no session is open; Video, Artwork, Small artwork (when the 3D stage painted any), Timeline and Log once one is
  const nav = document.querySelector('.workspace-nav');
  const tabs = nav ? [...nav.querySelectorAll('[data-tab]')] : [];
  let chosen = null, chosenJob = null;
  const hasJob = () => document.body.classList.contains('has-job');
  const currentJob = () => (typeof jobId !== 'undefined' && jobId) ? jobId : '';
  const currentState = () => (typeof state !== 'undefined' && state) ? state : null;
  function available(tab) {
    if (tab === 'home') return !hasJob();
    if (tab === 'project') return true;
    if (tab === 'timeline' && currentSongTimings()) return true;
    if (!hasJob()) return false;
    if (tab === 'video') return visible($('videoPanel'));
    if (tab === 'small') return !$('smallImagePanel')?.hidden;
    return true;
  }
  function currentTab() {
    if (!hasJob()) return ['project','timeline'].includes(chosen) && chosenJob === '' && available(chosen) ? chosen : 'home';
    if (chosen && chosenJob === currentJob() && available(chosen)) return chosen;
    return available('video') ? 'video' : 'artwork';
  }
  // The player gets the height left between its top edge and the bottom of the window (less the panel's padding),
  // so on a small window the whole video stays in view; width follows from its shape.
  function fitVideo() {
    const video = $('video');
    if (!video || !visible($('videoPanel')) || workspace?.dataset.tab !== 'video') return;
    const room = Math.max(180, Math.floor(window.innerHeight - video.getBoundingClientRect().top - 28));
    video.style.setProperty('--video-room', room + 'px');
  }
  window.addEventListener('resize', fitVideo);
  $('video')?.addEventListener('loadedmetadata', fitVideo);
  // The header's production area (pills, pipeline, progress, queue) collapses to the top bar, remembered between visits.
  const headerToggle = $('toggleHeader');
  function setHeader(collapsed) {
    document.body.classList.toggle('header-collapsed', collapsed);
    if (!headerToggle) return;
    headerToggle.setAttribute('aria-expanded', String(!collapsed));
    headerToggle.title = collapsed ? 'Expand the header' : 'Collapse the header';
  }
  setHeader(localStorage.getItem('lyricStudioHeaderCollapsed') === '1');
  headerToggle?.addEventListener('click', () => {
    const collapsed = !document.body.classList.contains('header-collapsed');
    // clipped while it slides, so the content does not spill out during the animation
    const production = $('headerProduction');
    document.body.classList.add('header-animating');
    const done = () => document.body.classList.remove('header-animating');
    production?.addEventListener('transitionend', event => { if (event.propertyName === 'max-height') done(); }, { once: true });
    setTimeout(done, 600);
    setHeader(collapsed);
    try { localStorage.setItem('lyricStudioHeaderCollapsed', collapsed ? '1' : '0'); } catch { /* private mode */ }
  });
  function syncTabs() {
    const tab = currentTab();
    if (workspace) workspace.dataset.tab = tab;
    if (tab === 'timeline') window.openStemTimeline?.(currentJob());
    if (tab === 'video') requestAnimationFrame(fitVideo);
    const counts = { artwork: $('gallery')?.querySelectorAll('.image-card').length || 0, small: $('smallImageGallery')?.querySelectorAll('.typography-picture').length || 0 };
    tabs.forEach(b => {
      const name = b.dataset.tab;
      b.hidden = !available(name);
      b.setAttribute('aria-selected', String(name === tab));
      const c = b.querySelector('.count'); if (c) c.textContent = counts[name] || '';
    });
  }
  // switching tabs cross-fades the workspace (a view transition), unless the system asks for less motion
  const fadeTo = change => (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches)
    ? (document.documentElement.classList.add('tab-fading'),
       document.startViewTransition(change).finished.finally(() => document.documentElement.classList.remove('tab-fading')))
    : change();
  tabs.forEach(b => b.addEventListener('click', () => fadeTo(() => { chosen = b.dataset.tab; chosenJob = currentJob(); syncTabs(); window.scrollTo({ top: 0, behavior: 'smooth' }); })));
  if (workspace) {
    const observer = new MutationObserver(syncTabs);
    ['videoPanel', 'gallery', 'reviewBanner', 'smallImagePanel'].forEach(id => { const el = $(id); if (el) observer.observe(el, { attributes: true, attributeFilter: ['hidden', 'style'], childList: true }); });
    new MutationObserver(syncTabs).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    syncTabs();
  }
  window.addEventListener('song-timings-changed', syncTabs);

  // ---- settings drawer
  const drawer = document.querySelector('aside.inspector');
  const form = $('jobForm');
  const sections = form ? [...form.querySelectorAll('details.section')] : [];
  const steps = { models: ['models', 'review', 'video', 'animation'], appearance: ['appearance'] };
  const stepBar = drawer?.querySelector('.step-bar');
  function setStep(step) {
    if (!drawer) return;
    if (!Object.hasOwn(steps, step)) step = 'models';
    drawer.dataset.step = step;
    stepBar?.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.step === step)));
    const wanted = steps[step];
    if (wanted) sections.forEach(d => { d.open = wanted.includes(d.dataset.section); });
    if (form) form.scrollTop = 0;
  }
  function openSettings(step) {
    document.body.classList.add('drawer-open');
    setStep(step || 'models');
    $('closeSettings')?.focus();
  }
  function closeSettings() { document.body.classList.remove('drawer-open'); $('openSettings')?.focus(); }
  window.openStudioSettings = openSettings;
  $('openSettings')?.addEventListener('click', () => document.body.classList.contains('drawer-open') ? closeSettings() : openSettings());
  $('closeSettings')?.addEventListener('click', closeSettings);
  // Starting over keeps the drawer open on the first step so the next song can be chosen straight away.
  window.showProjectTab = () => { chosen = 'project'; chosenJob = currentJob(); syncTabs(); window.scrollTo({ top: 0 }); };
  $('newSessionButton')?.addEventListener('click', () => setTimeout(() => { closeSettings(); window.showProjectTab(); }, 0));
  document.querySelector('.drawer-scrim')?.addEventListener('click', closeSettings);
  stepBar?.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    if (search?.value) { search.value = ''; applySearch(); }
    setStep(b.dataset.step);
  }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('drawer-open') && !document.querySelector('dialog[open]')) closeSettings(); });
  // Submitting the form (Generate) closes the drawer so the session takes the screen.
  form?.addEventListener('submit', () => setTimeout(() => { if (form.checkValidity()) closeSettings(); }, 50));

  // ---- collapsible sections remember their state; search filters fields across every section
  const stateKey = 'lyricStudioInspectorSections';
  try {
    const saved = JSON.parse(localStorage.getItem(stateKey) || 'null');
    if (saved) sections.forEach(d => { if (d.dataset.section in saved) d.open = !!saved[d.dataset.section]; });
  } catch {}
  let searching = false;
  sections.forEach(d => d.addEventListener('toggle', () => {
    if (searching) return;
    const state = {}; sections.forEach(s => state[s.dataset.section] = s.open);
    try { localStorage.setItem(stateKey, JSON.stringify(state)); } catch {}
  }));
  $('expandSections')?.addEventListener('click', () => sections.forEach(d => d.open = true));
  $('collapseSections')?.addEventListener('click', () => sections.forEach(d => d.open = false));

  const search = $('settingsSearch');
  let openBefore = null;
  const fields = form ? [...form.querySelectorAll('.section-body > fieldset > *, .section-body > :not(fieldset)')] : [];
  function applySearch() {
    const q = search.value.trim().toLowerCase();
    const note = $('settingsSearchNote');
    if (!q) {
      searching = false;
      fields.forEach(f => f.classList.remove('field-filtered'));
      if (openBefore) { sections.forEach((d, i) => d.open = openBefore[i]); openBefore = null; }
      sections.forEach(d => { const c = d.querySelector('.section-count'); if (c) c.textContent = ''; });
      if (note) note.textContent = '';
      if (drawer) delete drawer.dataset.searching;
      return;
    }
    if (!openBefore) openBefore = sections.map(d => d.open);
    if (drawer) drawer.dataset.searching = 'true';
    searching = true;
    let total = 0;
    sections.forEach(d => {
      let hits = 0;
      d.querySelectorAll('.section-body > fieldset > *, .section-body > :not(fieldset)').forEach(f => {
        const hit = f.textContent.toLowerCase().includes(q) || [...f.querySelectorAll('[placeholder],[title],[name]')].some(el => (el.placeholder + ' ' + el.title + ' ' + el.name).toLowerCase().includes(q));
        f.classList.toggle('field-filtered', !hit); if (hit) hits++;
      });
      const titleHit = (d.querySelector('.section-title')?.textContent || '').toLowerCase().includes(q);
      if (titleHit && !hits) { d.querySelectorAll('.field-filtered').forEach(f => f.classList.remove('field-filtered')); hits = d.querySelectorAll('.section-body > *').length; }
      d.open = hits > 0; total += hits;
      const c = d.querySelector('.section-count'); if (c) c.textContent = hits ? String(hits) : '';
    });
    if (note) note.textContent = total ? '' : 'No setting matches “' + search.value.trim() + '”.';
  }
  if (search) {
    search.addEventListener('input', applySearch);
    search.addEventListener('keydown', event => { if (event.key === 'Escape') { search.value = ''; applySearch(); search.blur(); } });
    document.addEventListener('keydown', event => {
      if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) && !document.activeElement?.isContentEditable && !document.querySelector('dialog[open]')) {
        event.preventDefault(); openSettings(drawer?.dataset.step || 'models'); search.focus(); search.select();
      }
    });
  }
  // A section opens (and the drawer with it) when a control inside is focused by script or fails validation.
  form?.addEventListener('focusin', event => { const d = event.target.closest('details.section'); if (d && !d.open) d.open = true; });
  form?.addEventListener('invalid', event => { const d = event.target.closest('details.section'); if (d) { document.body.classList.add('drawer-open'); if (search?.value) { search.value = ''; applySearch(); } setStep(d.dataset.section === 'appearance' ? 'appearance' : 'models'); d.open = true; } }, true);
  document.addEventListener('invalid', event => { if (event.target.closest?.('#projectPanel')) { closeSettings(); window.showProjectTab(); } }, true);
  // The Project tab's Generate mirrors the form's submit button, which the session scripts enable and explain.
  const generate = $('generate'), proxy = $('generateProject'), reason = $('generateReason'), proxyReason = $('projectReason');
  if (generate && proxy) {
    const mirror = () => { proxy.disabled = generate.disabled; proxy.title = generate.title; if (proxyReason) proxyReason.textContent = reason?.textContent || ''; };
    new MutationObserver(mirror).observe(generate, { attributes: true });
    if (reason) new MutationObserver(mirror).observe(reason, { childList: true, characterData: true, subtree: true });
    proxy.addEventListener('click', () => generate.click());
    mirror();
  }

  // ---- section subtitles mirror the live choice so a collapsed section still tells you what it holds
  const subs = {
    song: () => $('audio')?.files[0]?.name || ($('profileAudioStatus')?.textContent || '').replace(/^Audio ready · /, '') || 'No audio selected',
    models: () => $('imageModel')?.selectedOptions[0]?.textContent || 'Choose models',
    prompts: () => ($('style')?.value || '').trim().split(/[.;]/)[0] || 'Visual style',
    review: () => ($('autoAccept')?.checked ? 'Auto-accept' : 'Manual approval') + ($('autoRepair')?.checked ? ' · auto-repair' : ''),
    video: () => [$('resolution')?.selectedOptions[0]?.textContent, $('audioMode')?.value === 'karaoke' ? 'Karaoke' : null].filter(Boolean).join(' · '),
    typography: () => [$('readingFlow')?.selectedOptions[0]?.textContent?.split(':')[0], $('fontFamily')?.selectedOptions[0]?.textContent].filter(Boolean).join(' · '),
    run: () => $('startStep')?.selectedOptions[0]?.textContent?.replace(/\s*\(.*\)$/, '') || '',
    animation: () => 'Off',
    timing: () => 'Word timing editor'
  };
  function refreshSubs() { sections.forEach(d => { const s = d.querySelector('.section-sub'); const f = subs[d.dataset.section]; if (s && f) { try { s.textContent = f() || ''; } catch { s.textContent = ''; } } }); }
  if (form) { form.addEventListener('change', refreshSubs); form.addEventListener('input', refreshSubs); setInterval(refreshSubs, 2500); refreshSubs(); }
  form?.addEventListener('change', () => { if (typeof state !== 'undefined' && state && typeof updateRebuildNotice === 'function') updateRebuildNotice(state); });
  // Project-panel fields belong to the form but sit outside it, so their changes do not bubble to it.
  document.addEventListener('change', event => { if (!event.target.closest?.('#projectPanel')) return; refreshSubs(); if (typeof state !== 'undefined' && state && typeof updateRebuildNotice === 'function') updateRebuildNotice(state); });

  // ---- the run option's explanation rides on the select as a tooltip (its help text is hidden in the header)
  const stepHelp = $('stepHelp'), startStep = $('startStep');
  if (stepHelp && startStep) { const mirrorHelp = () => { startStep.title = stepHelp.textContent.trim(); }; new MutationObserver(mirrorHelp).observe(stepHelp, { childList: true, characterData: true, subtree: true }); mirrorHelp(); }

  // ---- theme: Auto follows the system, Light and Dark override it; the choice is kept in this browser
  const themeButton = $('themeToggle');
  const themeOrder = ['', 'light', 'dark'];
  const themeNames = { '': 'Auto', light: 'Light', dark: 'Dark' };
  function applyTheme(value, save) {
    if (value) document.documentElement.dataset.theme = value; else delete document.documentElement.dataset.theme;
    if (themeButton) { themeButton.querySelector('.theme-label').textContent = themeNames[value]; themeButton.setAttribute('aria-label', 'Theme: ' + (value ? themeNames[value] : 'follows system') + '. Click to change'); }
    if (save) { try { value ? localStorage.setItem('lyricStudioTheme', value) : localStorage.removeItem('lyricStudioTheme'); } catch {} }
  }
  let storedTheme = ''; try { storedTheme = localStorage.getItem('lyricStudioTheme') || ''; } catch {}
  applyTheme(themeOrder.includes(storedTheme) ? storedTheme : '', false);
  themeButton?.addEventListener('click', () => {
    const now = document.documentElement.dataset.theme || '';
    const next = themeOrder[(themeOrder.indexOf(now) + 1) % themeOrder.length];
    const change = () => applyTheme(next, true);
    // a slow cross-fade of the whole page between the two themes
    if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.documentElement.classList.add('theme-fading');
      document.startViewTransition(change).finished.finally(() => document.documentElement.classList.remove('theme-fading'));
    } else {
      document.documentElement.classList.add('theme-easing');
      change();
      setTimeout(() => document.documentElement.classList.remove('theme-easing'), 900);
    }
  });

  // ---- the gallery's plain notices get the same treatment as the rest
  const gallery = $('gallery');
  function decorateEmpty() {
    const empty = gallery?.querySelector(':scope > .empty');
    if (!empty || empty.querySelector('h3') || empty.dataset.decorated) return;
    const text = empty.textContent.trim();
    empty.dataset.decorated = '1';
    if (/Loading job/.test(text)) { empty.innerHTML = '<div class="empty-symbol spin" aria-hidden="true">◌</div><h3>Loading</h3><p>Fetching artwork, timings and video…</p>'; return; }
    if (/Choose your audio/.test(text)) { empty.innerHTML = '<div class="empty-symbol" aria-hidden="true">▧</div><h3>No artwork yet</h3><p>Illustrations appear here as they are painted.</p>'; return; }
    empty.innerHTML = '<div class="empty-symbol" aria-hidden="true">▧</div><h3>Nothing to show yet</h3><p></p>'; empty.querySelector('p').textContent = text;
  }
  if (gallery) { new MutationObserver(decorateEmpty).observe(gallery, { childList: true }); decorateEmpty(); }

  // ---- backdrop: the open session's poster (or the newest finished video at home) blurred behind the glass
  const backdrop = document.querySelector('.backdrop');
  let backdropUrl = '';
  function syncBackdrop() {
    if (!backdrop) return;
    const url = hasJob() ? (currentState()?.poster || '') : (window.homePoster || '');
    if (url === backdropUrl) return;
    backdropUrl = url;
    if (!url) { backdrop.classList.remove('show'); return; }
    const img = new Image();
    img.onload = () => { backdrop.style.backgroundImage = `url("${url}")`; backdrop.classList.add('show'); };
    img.src = url;
  }
  setInterval(syncBackdrop, 1500); syncBackdrop();

  // ---- the body carries the job status (complete, running, review…) for styles that depend on it
  const statusBadge = $('status');
  const syncStatus = () => { document.body.dataset.jobStatus = (statusBadge?.textContent || '').trim().toLowerCase(); };
  if (statusBadge) { new MutationObserver(syncStatus).observe(statusBadge, { childList: true, characterData: true, subtree: true }); syncStatus(); }

  // ---- the pipeline rail scrolls sideways with the wheel when it is wider than its room
  const rail = $('stages');
  // each edge of the rail fades while there is more rail beyond it, and stops fading once that end is reached
  const markOverflow = () => {
    if (!rail) return;
    const wider = rail.scrollWidth > rail.clientWidth + 2, host = rail.parentElement;
    host.classList.toggle('more-left', wider && rail.scrollLeft > 2);
    host.classList.toggle('more-right', wider && rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 2);
  };
  if (rail) { new ResizeObserver(markOverflow).observe(rail); new MutationObserver(markOverflow).observe(rail, { childList: true, subtree: true }); rail.addEventListener('scroll', markOverflow, { passive: true }); markOverflow(); }
  rail?.addEventListener('wheel', event => { if (rail.scrollWidth > rail.clientWidth && Math.abs(event.deltaY) > Math.abs(event.deltaX)) { rail.scrollLeft += event.deltaY; event.preventDefault(); } }, { passive: false });

  // ---- the rail is dragged with the left button or a finger, from a stage or the background around it. A press only
  // counts as a drag once it has moved, so a click on a stage still chooses it.
  const flow = document.querySelector('.deck-flow');
  if (flow && rail) {
    let drag = null, dragged = false;
    flow.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = { id: event.pointerId, x: event.clientX, left: rail.scrollLeft };
      dragged = false;
    });
    flow.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.id) return;
      const moved = event.clientX - drag.x;
      if (!dragged && Math.abs(moved) < 5) return;
      if (!dragged) { dragged = true; flow.setPointerCapture(drag.id); flow.classList.add('dragging'); }
      rail.scrollLeft = drag.left - moved;
    });
    const drop = () => { drag = null; flow.classList.remove('dragging'); };
    flow.addEventListener('pointerup', drop);
    flow.addEventListener('pointercancel', drop);
    flow.addEventListener('click', event => {
      if (dragged) { event.preventDefault(); event.stopPropagation(); dragged = false; }
    }, true);
  }

  // ---- Settings > Projects folder: read when the studio starts, so a new one is used from the next start
  window.initProjectsFolder = cfg => {
    const input = $('projectsFolder'), save = $('saveProjectsFolder'), help = $('projectsFolderHelp');
    if (!input) return;
    const note = folder => { help.textContent = `Now in use: ${cfg.projects_folder}. ` + (folder && folder !== cfg.projects_folder ? `Restart the studio to use ${folder}. ` : '') + 'Existing projects are not moved. Leave empty for the default.'; };
    input.value = cfg.projects_folder_saved || '';
    input.placeholder = cfg.projects_folder_default || '';
    input.disabled = save.disabled = !!cfg.projects_folder_fixed;
    if (cfg.projects_folder_fixed) { help.textContent = `Set by KINETIC_LYRICS_OUTPUT: ${cfg.projects_folder}.`; return; }
    note('');
    save.onclick = async () => {
      try {
        const reply = await api('/api/projects-folder', { path: input.value });
        note(reply.folder);
        toast(reply.restart ? 'Saved. Restart the studio to use this folder.' : 'Saved.');
      } catch (error) { toast(error.message); }
    };
  };

  // ---- log drawer toggle
  $('toggleLog')?.addEventListener('click', () => {
    const panel = $('logPanel'); const collapsed = panel.classList.toggle('collapsed');
    $('toggleLog').textContent = collapsed ? 'Expand' : 'Collapse'; $('toggleLog').setAttribute('aria-expanded', String(!collapsed));
  });
})();
