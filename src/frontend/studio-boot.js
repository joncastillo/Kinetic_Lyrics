// Runs in the head, before the page paints: restores the theme, and the backdrop and panel colour chosen for it in
// this browser's active profile, so the first frame already looks right. studio-appearance.js reuses the helpers.
(() => {
  const PROFILE_KEY = 'lyricStudioProfilesV1';
  const DEFAULT_BACKDROP = { light: '/studio-art/day-meadow.webp', dark: '/studio-art/night-osaka-lanterns.webp' };
  const PANEL_VARS = ['--s1', '--s2', '--glass', '--glass-2', '--glass-3', '--pop', '--bg'];
  let videoUrl = '', sceneVideo = null, layerOverrides = {};
  let rotationKey = '', rotationUrls = [], rotationIndex = 0, rotationTimer = 0, displayUrl = '', displayPicture = '';
  let transition = null, transitionTimer = 0, revision = 0;
  const motion = matchMedia('(prefers-reduced-motion:reduce)');
  function playScene(){}
  function videoBackdrop(){}
  document.addEventListener('DOMContentLoaded', () => videoBackdrop(videoUrl, layerOverrides));
  document.addEventListener('visibilitychange', playScene);
  motion.addEventListener('change', playScene);

  function read() {
    try {
      const profiles = JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}') || {};
      const active = localStorage.getItem(PROFILE_KEY + 'Active');
      const raw = (profiles[active] || {}).settings?.appearance;
      const value = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
      return value && typeof value === 'object' ? value : {};
    } catch { return {}; }
  }
  const theme = () => document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');

  // Panel colour: one hex tints the surfaces and glass layers the theme draws panels with; no colour restores the theme's own.
  function paint(hex) {
    const root = document.documentElement.style;
    if (!/^#[0-9a-f]{6}$/i.test(hex || '')) { PANEL_VARS.forEach(v => root.removeProperty(v)); return; }
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    const mix = (c, to, k) => Math.round(c + (to - c) * k);
    const tone = (k, to, a) => `rgba(${mix(r, to, k)},${mix(g, to, k)},${mix(b, to, k)},${a})`;
    root.setProperty('--s1', tone(.2, 0, .74)); root.setProperty('--s2', tone(.05, 0, .82));
    root.setProperty('--glass', tone(.18, 255, .34)); root.setProperty('--glass-2', tone(.26, 255, .42)); root.setProperty('--glass-3', tone(.36, 255, .5));
    root.setProperty('--pop', tone(.25, 0, .92)); root.setProperty('--bg', `rgb(${mix(r, 0, .6)},${mix(g, 0, .6)},${mix(b, 0, .6)})`);
  }
  function snapshot(){return null;}
  function showBackdrop(url, layers, crossfade = false) {
    const token = ++revision;
    clearTimeout(transitionTimer); transition?.remove(); transition = null;
    const cover = crossfade && !motion.matches ? snapshot() : null; transition = cover;
    document.documentElement.dataset.backdropTransition = String(!!cover);
    const isScene = /\.scene\.json$/i.test(url || ''), isVideo = /\.mp4$/i.test(url || '');
    displayUrl = url; displayPicture = isScene ? url.replace(/\.scene\.json$/i, '.webp') : isVideo ? url.replace(/\.mp4$/i, '.webp') : url;
    document.documentElement.dataset.animatedBackdrop = String(isScene || isVideo);
    document.documentElement.style.setProperty('--scene', displayPicture ? `url(${displayPicture})` : 'none');
    let ready = videoBackdrop(isScene || isVideo ? url : '', layers);
    if (!isScene && !isVideo && url && cover) ready = new Promise(resolve => { const img = new Image(); img.onload = img.onerror = resolve; img.src = url; });
    if (typeof CustomEvent === 'function') document.dispatchEvent(new CustomEvent('studio-backdrop-change', {detail:{url}}));
    if (cover) Promise.race([Promise.resolve(ready), new Promise(resolve => setTimeout(resolve, 8000))]).then(() => {
      if (token !== revision) return;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (token !== revision) return;
        cover.style.opacity = '0'; transitionTimer = setTimeout(() => {
          cover.remove();
          if (transition === cover) { transition = null; document.documentElement.dataset.backdropTransition = 'false'; }
        }, 1800);
      }));
    });
  }
  function apply(appearance) {
    const t = theme(), choice = (appearance || {})[t] || {};
    const url = typeof choice.backdrop === 'string' ? choice.backdrop : DEFAULT_BACKDROP[t];
    const saved = Array.isArray(choice.backdrops) ? choice.backdrops : Array.isArray(choice.backdrop) ? choice.backdrop : [];
    const selected = [...new Set(saved.filter(v => typeof v === 'string'))];
    const urls = selected.length ? selected : [url], key = JSON.stringify([t, urls]);
    layerOverrides = choice.layers || {};
    if (key !== rotationKey) {
      rotationKey = key; rotationUrls = urls; rotationIndex = 0; clearInterval(rotationTimer);
      showBackdrop(urls[0], layerOverrides);
      rotationTimer = urls.length > 1 ? setInterval(() => {
        if (document.hidden) return;
        rotationIndex = (rotationIndex + 1) % rotationUrls.length;
        showBackdrop(rotationUrls[rotationIndex], layerOverrides, true);
      }, 60000) : 0;
    } else videoBackdrop(/\.scene\.json$|\.mp4$/i.test(displayUrl || '') ? displayUrl : '', layerOverrides);
    paint(choice.panel);
  }

  try { const kl = localStorage.getItem('lyricStudioTheme'); if (kl === 'light' || kl === 'dark') document.documentElement.dataset.theme = kl; } catch {}
  window.studioAppearance = { PROFILE_KEY, DEFAULT_BACKDROP, theme, paint, apply, read, activeBackdrop: () => displayUrl };
  apply(read());
})();
