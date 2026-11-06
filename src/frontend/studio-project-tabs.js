// Project panel sub-tabs: Song, Story, References, Artwork, Typography, Effects. The preset box and the tab rail
// stay in place; the chosen tab is remembered in this browser, and a field that fails validation brings its tab forward.
(() => {
  const panel = document.getElementById('projectPanel');
  if (!panel) return;
  const tabs = [...panel.querySelectorAll('.subtabs [data-ptab]')], panes = [...panel.querySelectorAll('.ptab[data-ptab]')];
  const KEY = 'lyricStudioProjectTab';
  function show(name, save = true) {
    if (!tabs.some(tab => tab.dataset.ptab === name)) name = 'song';
    panel.dataset.ptab = name;
    tabs.forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.ptab === name)));
    panes.forEach(pane => { pane.hidden = pane.dataset.ptab !== name; });
    if (save) { try { localStorage.setItem(KEY, name); } catch {} }
  }
  tabs.forEach(tab => tab.addEventListener('click', () => show(tab.dataset.ptab)));
  document.addEventListener('invalid', event => { const pane = event.target.closest?.('#projectPanel .ptab'); if (pane) show(pane.dataset.ptab); }, true);
  window.showProjectSubtab = show;

  // Lyric split: one form field ("auto", a count, or a pattern such as 2-3-2-4) behind a mode select.
  const lines = document.getElementById('lines'), mode = document.getElementById('linesMode'), field = document.getElementById('linesField');
  if (lines && mode && field) {
    // "2-" is a pattern being typed, not Auto: the field stays open for the next number
    const modeOf = value => /^\d+(-\d*)+$/.test(value) ? 'manual' : /^\d+$/.test(value) ? 'equal' : 'auto';
    const typing = () => document.activeElement === lines && mode.value !== 'auto' && lines.value.trim().toLowerCase() !== 'auto';
    const reflect = () => {
      const current = typing() ? mode.value : modeOf(lines.value.trim()); mode.value = current;
      field.hidden = current === 'auto';
      lines.placeholder = current === 'manual' ? 'e.g. 2-3-2-4' : '1–50'; lines.inputMode = current === 'manual' ? 'text' : 'numeric';
    };
    mode.addEventListener('change', () => {
      const current = modeOf(lines.value.trim());
      if (mode.value !== current) { lines.value = mode.value === 'auto' ? 'auto' : mode.value === 'equal' ? '3' : '2-3-2-4'; lines.dispatchEvent(new Event('change', { bubbles: true })); }
      reflect(); if (mode.value !== 'auto') lines.focus();
    });
    lines.addEventListener('input', reflect);
    lines.addEventListener('blur', () => {  // a dash left at the end is dropped, so the run gets a whole pattern
      const tidy = lines.value.trim().replace(/-+$/, '');
      if (tidy !== lines.value) { lines.value = tidy || (mode.value === 'manual' ? '2-3-2-4' : 'auto'); lines.dispatchEvent(new Event('change', { bubbles: true })); }
      reflect();
    });
    new MutationObserver(reflect).observe(lines, { attributes: true, attributeFilter: ['value'] });
    setInterval(() => { if (!typing() && mode.value !== modeOf(lines.value.trim())) reflect(); }, 700);  // profiles and session restore set the value silently
    reflect();
  }

  // The lyric split, in the lyrics box itself: a layer behind the textarea (same box, font and wrapping) tints each
  // image's lines in that image's colour and numbers the image in a gutter, so a manual or equal split can be
  // checked before generating. Lines are counted as the pipeline counts them: non-empty, without [section] labels.
  const lyrics = document.getElementById('lyrics'), marks = document.getElementById('lyricsMarks'), box = lyrics?.closest('.lyrics-box');
  if (lyrics && lines && marks && box) {
    const HUES = [210, 28, 140, 330, 265, 55, 185, 0];
    const counted = line => { const text = line.trim(); return text && !/^\[.*\]$/.test(text); };
    const render = () => {
      const value = lines.value.trim();
      const pattern = /^\d+(-\d+)+$/.test(value) ? value.split('-').map(Number) : /^\d+$/.test(value) ? [Math.max(1, +value)] : null;
      const rows = lyrics.value.split(/\r?\n/);
      box.classList.toggle('split', !!pattern);
      marks.replaceChildren();
      if (!pattern) return;
      // which image each counted line falls in, cycling the pattern as the pipeline does
      let image = 0, left = pattern[0], k = 0, previous = null;
      const blocks = rows.map(row => {
        const block = document.createElement('span'); block.className = 'lyrics-mark'; block.textContent = row;
        if (counted(row)) {
          if (!left) { image++; k++; left = pattern[k % pattern.length]; }
          block.classList.add('in'); block.style.setProperty('--split-hue', HUES[image % HUES.length]);
          if (previous !== image) { block.classList.add('first'); block.append(Object.assign(document.createElement('i'), { className: 'lyrics-mark-number', textContent: String(image + 1) })); }
          previous = image; left--;
          if (!left) block.classList.add('last');
        }
        return block;
      });
      marks.append(...blocks);
      follow();
    };
    // the textarea's scrollbar narrows its text; the layer keeps the same width and scroll position
    const follow = () => { marks.style.right = (lyrics.offsetWidth - lyrics.clientWidth - 2) + 'px'; marks.scrollTop = lyrics.scrollTop; };
    let timer = 0; const later = () => { clearTimeout(timer); timer = setTimeout(render, 150); };
    lyrics.addEventListener('input', later); lines.addEventListener('input', later); lines.addEventListener('change', later);
    mode?.addEventListener('change', later);
    lyrics.addEventListener('scroll', follow); new ResizeObserver(follow).observe(lyrics);
    setInterval(() => { const key = lyrics.value.length + '|' + lines.value; if (key !== marks.dataset.key) { marks.dataset.key = key; render(); } }, 800);
    render();
  }
  let saved = ''; try { saved = localStorage.getItem(KEY) || ''; } catch {}
  show(saved || 'song', false);
})();
