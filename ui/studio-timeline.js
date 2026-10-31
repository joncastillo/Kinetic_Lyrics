/* Stem waveforms and exact lyric word times for the selected Studio job. */
(() => {
  const panel = document.getElementById('videoPanel');
  const heading = panel?.querySelector('.panel-head');
  if (!heading) return;
  const openButton = document.createElement('button');
  openButton.type = 'button';
  openButton.id = 'openTimeline';
  openButton.textContent = 'Open stem timeline';
  heading.insertBefore(openButton, heading.querySelector('#download'));

  const dialog = document.createElement('dialog');
  dialog.id = 'timelineDialog';
  dialog.className = 'timeline-dialog';
  dialog.innerHTML = `
    <div class="timeline-heading"><div><div class="eyebrow">Lyric timing</div><h2>Stem timeline</h2>
      <p class="help">Drag a word to move it, or drag its edges to change where it starts and ends. Drag empty space
      to scroll, use the mouse wheel to zoom (Shift + wheel scrolls), and click to play from that point.</p></div>
      <button type="button" id="closeTimeline">Close</button></div>
    <audio id="timelineAudio" controls preload="metadata"></audio>
    <div class="timeline-tools">
      <button type="button" id="timelineZoomOut" title="Zoom out">−</button>
      <button type="button" id="timelineZoomIn" title="Zoom in">+</button>
      <button type="button" id="timelineFitLine">Fit line</button>
      <button type="button" id="timelineWhole">Whole song</button>
      <label>Position <input id="timelinePosition" type="range" min="0" value="0" step="0.001"></label>
      <span id="timelineRange"></span></div>
    <div id="timelineTracks" class="timeline-tracks"></div>
    <div class="timeline-edit"><div id="timelineLines" class="timeline-lines"></div>
      <div class="timeline-word-panel"><h3 id="timelineLineTitle">Choose a lyric line</h3>
      <div id="timelineWords" class="timeline-words"></div><div class="row timeline-actions">
      <button type="button" id="saveTimeline" class="primary">Save timings</button>
      <button type="button" id="rerenderTimeline">Rebuild video</button>
      <span id="timelineStatus" role="status"></span></div></div></div>
    <div id="timelineUnsaved" class="timeline-unsaved" hidden role="alertdialog" aria-label="Unsaved timing changes">
      <span>You have unsaved timing changes.</span>
      <button type="button" id="timelineSaveClose" class="primary">Save and close</button>
      <button type="button" id="timelineDiscard" class="danger">Discard changes</button>
      <button type="button" id="timelineKeep">Keep editing</button></div>`;
  document.body.append(dialog);
  const find = id => dialog.querySelector('#' + id);
  const audio = find('timelineAudio');
  const tracks = find('timelineTracks');
  const position = find('timelinePosition');
  const COLORS = ['213,245,155', '118,214,255', '255,184,107', '229,155,255'];
  const EDGE = 6, MIN_WORD = .02, MIN_SPAN = .5;
  let data = null, words = [], selectedLine = 0, changed = false, frame = 0, openedJob = '';
  let begin = 0, span = 24, hover = null, drag = null;
  // Undo history: each edit is one word's times before and after; `saved` marks the position last saved.
  let history = [], cursor = 0, saved = 0;

  // m:ss.mmm, the format used everywhere in the editor; typed values may also be plain seconds.
  const stamp = t => {
    const ms = Math.max(0, Math.round(t * 1000));
    return `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`;
  };
  const parseStamp = text => {
    const value = text.trim().match(/^(?:(\d+):)?(\d+(?:\.\d{0,3})?)$/);
    return value ? Number(value[1] || 0) * 60 + Number(value[2]) : NaN;
  };
  const round = t => Math.round(t * 1000) / 1000;
  const lineStart = line => Number(line.words[0].start);
  const lineEnd = line => Number(line.words.at(-1).end);

  function setView(start, size) {
    span = Math.min(data.duration, Math.max(MIN_SPAN, size));
    begin = Math.min(Math.max(0, start), Math.max(0, data.duration - span));
    position.max = String(Math.max(0, data.duration - span));
    position.value = String(begin);
    find('timelineRange').textContent = `${stamp(begin)} – ${stamp(begin + span)} · ${span < 10 ? span.toFixed(2) : Math.round(span)} s`;
  }
  const zoomAround = (anchor, factor, fraction = .5) => { const size = Math.min(data.duration, Math.max(MIN_SPAN, span * factor)); setView(anchor - fraction * size, size); };
  const fitLine = index => {
    const line = data.timings[index], length = lineEnd(line) - lineStart(line);
    setView(lineStart(line) - length * .15 - .3, length * 1.3 + .6);
  };

  function wordAt(canvas, x) {
    const width = canvas.clientWidth, t = begin + x / width * span, slack = EDGE / width * span;
    let best = null;
    for (const entry of words) {
      const { word } = entry, start = Number(word.start), end = Number(word.end);
      if (end < begin || start > begin + span || t < start - slack || t > end + slack) continue;
      const part = Math.abs(t - start) <= slack ? 'start' : Math.abs(t - end) <= slack ? 'end' : t >= start && t <= end ? 'move' : null;
      if (part && (!best || part !== 'move')) best = { entry, part };
    }
    return best;
  }

  const snapshot = entries => new Map(entries.filter(Boolean).map(entry => [entry.flat, { start: Number(entry.word.start), end: Number(entry.word.end) }]));

  // Neighbours bound each drag so words never overlap or reverse. A boundary two words share (one ends where the
  // next begins) moves for both, so touching words can be retimed; existing overlaps are left as they were.
  function moveWord(entry, part, before, delta) {
    const { flat } = entry, previous = words[flat - 1], next = words[flat + 1];
    const own = before.get(flat), prior = previous && before.get(previous.flat), after = next && before.get(next.flat);
    const sharedBefore = prior && Math.abs(prior.end - own.start) < .0015, sharedAfter = after && Math.abs(after.start - own.end) < .0015;
    const low = sharedBefore ? prior.start + MIN_WORD : prior ? Math.min(prior.end, own.start) : 0;
    const high = sharedAfter ? after.end - MIN_WORD : after ? Math.max(after.start, own.end) : data.duration;
    let start = own.start, end = own.end;
    if (part === 'move') {
      const shift = Math.min(Math.max(delta, low - own.start), high - own.end);
      start += shift; end += shift;
    } else if (part === 'start') start = Math.min(Math.max(low, own.start + delta), own.end - MIN_WORD);
    else end = Math.max(Math.min(high, own.end + delta), own.start + MIN_WORD);
    entry.word.start = round(start); entry.word.end = round(end);
    if (sharedBefore && part !== 'end') previous.word.end = entry.word.start;
    if (sharedAfter && part !== 'start') next.word.start = entry.word.end;
    if (entry.line === selectedLine || previous?.line === selectedLine || next?.line === selectedLine) refreshWordInputs();
  }

  function markChanged(line) {
    changed = cursor !== saved;
    find('timelineStatus').textContent = changed ? 'Unsaved timing changes · Ctrl+Z to undo' : (data.needs_render ? 'Saved. Rebuild the video to apply.' : '');
    if (line === selectedLine) refreshWordInputs();
    renderLines();
  }

  // One undo step per drag or typed value, covering every word it changed.
  function record(before) {
    const changes = [...before].map(([flat, old]) => ({ flat, before: old, after: { start: Number(words[flat].word.start), end: Number(words[flat].word.end) } }))
      .filter(change => change.after.start !== change.before.start || change.after.end !== change.before.end);
    if (!changes.length) return;
    history = history.slice(0, cursor); if (saved > cursor) saved = -1;
    history.push(changes); cursor = history.length;
    markChanged(words[changes[0].flat].line);
  }

  function step(direction) {
    const changes = direction < 0 ? history[cursor - 1] : history[cursor];
    if (!changes) return;
    cursor += direction;
    for (const change of changes) Object.assign(words[change.flat].word, direction < 0 ? change.before : change.after);
    const entry = words[changes[0].flat];
    if (entry.line !== selectedLine) selectLine(entry.line, false);
    const start = Number(entry.word.start);
    if (start < begin || start > begin + span) setView(start - span * .3, span);
    markChanged(entry.line);
  }

  function draw() {
    if (!data || !dialog.open) return;
    cancelAnimationFrame(frame);
    if (!audio.paused && audio.currentTime > begin + span * .95) setView(audio.currentTime - span * .1, span);
    const ratio = window.devicePixelRatio || 1;
    for (const row of tracks.querySelectorAll('.timeline-track')) {
      const canvas = row.querySelector('canvas');
      const cssWidth = canvas.clientWidth, cssHeight = canvas.clientHeight;
      if (canvas.width !== Math.round(cssWidth * ratio) || canvas.height !== Math.round(cssHeight * ratio)) {
        canvas.width = Math.round(cssWidth * ratio); canvas.height = Math.round(cssHeight * ratio);
      }
      const context = canvas.getContext('2d');
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const width = cssWidth, height = cssHeight, vocals = row.dataset.stem === 'vocals';
      const x = t => (t - begin) / span * width;
      context.fillStyle = '#111a19'; context.fillRect(0, 0, width, height);
      // Word blocks first, so the waveform reads on top of them.
      context.font = '11px "Segoe UI", sans-serif'; context.textBaseline = 'top';
      for (const entry of words) {
        const start = Number(entry.word.start), end = Number(entry.word.end);
        if (end < begin || start > begin + span) continue;
        const left = x(start), right = x(end), color = COLORS[entry.flat % COLORS.length];
        const active = entry.line === selectedLine, focused = hover?.entry === entry || drag?.entry === entry;
        const playing = audio.currentTime >= start && audio.currentTime < end;
        context.fillStyle = `rgba(${color},${focused ? .42 : active ? .28 : .12})`;
        context.fillRect(left, 0, right - left, height);
        if (active || focused || playing) {
          context.fillStyle = `rgba(${color},${focused ? 1 : .75})`;
          context.fillRect(left, 0, 1.5, height); context.fillRect(right - 1.5, 0, 1.5, height);
        }
        if (playing) { context.strokeStyle = `rgb(${color})`; context.lineWidth = 1; context.strokeRect(left + .5, .5, right - left - 1, height - 1); }
        if (vocals && right - left > context.measureText(entry.word.text).width + 6) {
          context.fillStyle = `rgba(${color},${active || focused ? 1 : .7})`;
          context.fillText(entry.word.text, left + 3, 3);
        }
      }
      const peaks = data.stems[row.dataset.stem].peaks;
      context.fillStyle = vocals ? 'rgba(241,243,233,.75)' : 'rgba(112,184,210,.8)';
      const first = Math.max(0, Math.floor(begin / data.duration * peaks.length));
      const last = Math.min(peaks.length, Math.ceil((begin + span) / data.duration * peaks.length));
      const bar = width / peaks.length * data.duration / span;
      for (let i = first; i < last; i++) {
        const level = Math.min(1, peaks[i] * 2.1);
        context.fillRect(x(i / peaks.length * data.duration), height * (1 - level) / 2, Math.max(1, bar - (bar > 3 ? 1 : 0)), Math.max(1, height * level));
      }
      const cursor = x(audio.currentTime);
      if (cursor >= 0 && cursor <= width) { context.fillStyle = '#ffbd76'; context.fillRect(cursor - 1, 0, 2, height); }
    }
    frame = requestAnimationFrame(draw);
  }

  function attach(canvas) {
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const hit = wordAt(canvas, event.offsetX);
      canvas.setPointerCapture(event.pointerId);
      drag = hit ? { entry: hit.entry, part: hit.part, before: snapshot([words[hit.entry.flat - 1], hit.entry, words[hit.entry.flat + 1]]) }
                 : { pan: true, viewBegin: begin };
      Object.assign(drag, { x: event.offsetX, moved: false });
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag) {
        hover = wordAt(canvas, event.offsetX);
        canvas.style.cursor = !hover ? 'grab' : hover.part === 'move' ? 'move' : 'ew-resize';
        return;
      }
      const dx = event.offsetX - drag.x;
      if (Math.abs(dx) > 3) drag.moved = true;
      if (!drag.moved) return;
      const seconds = dx / canvas.clientWidth * span;
      if (drag.pan) { canvas.style.cursor = 'grabbing'; setView(drag.viewBegin - seconds, span); }
      else moveWord(drag.entry, drag.part, drag.before, seconds);
    });
    const finish = event => {
      if (!drag) return;
      if (drag.moved && drag.entry) record(drag.before);
      if (!drag.moved) {
        if (drag.pan) audio.currentTime = begin + event.offsetX / canvas.clientWidth * span;
        else {
          if (drag.entry.line !== selectedLine) selectLine(drag.entry.line, false);
          audio.currentTime = Number(drag.entry.word.start);
        }
      }
      drag = null; canvas.style.cursor = 'grab';
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', () => {
      if (drag?.moved && drag.entry) for (const [flat, old] of drag.before) Object.assign(words[flat].word, old);
      drag = null;
    });
    canvas.addEventListener('pointerleave', () => { if (!drag) hover = null; });
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      const fraction = event.offsetX / canvas.clientWidth;
      if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        setView(begin + (event.deltaX || event.deltaY) / canvas.clientWidth * span, span);
      } else zoomAround(begin + fraction * span, Math.exp(event.deltaY * .0015), fraction);
    }, { passive: false });
  }

  function renderLines() {
    const list = find('timelineLines'); list.replaceChildren();
    data.timings.forEach((line, index) => {
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'timeline-line' + (index === selectedLine ? ' selected' : '');
      button.textContent = `${stamp(lineStart(line))}  ${line.text}`;
      button.onclick = () => selectLine(index);
      list.append(button);
    });
  }

  function refreshWordInputs() {
    for (const input of find('timelineWords').querySelectorAll('input')) {
      if (document.activeElement !== input) input.value = stamp(Number(data.timings[selectedLine].words[input.dataset.index][input.dataset.key]));
    }
  }

  function selectLine(index, moveView = true) {
    selectedLine = index;
    const line = data.timings[index];
    find('timelineLineTitle').textContent = `Line ${index + 1}: ${line.text}`;
    const list = find('timelineWords'); list.replaceChildren();
    line.words.forEach((word, wordIndex) => {
      const row = document.createElement('div'); row.className = 'timeline-word';
      const label = document.createElement('strong'); label.textContent = word.text;
      row.append(label);
      for (const key of ['start', 'end']) {
        const field = document.createElement('label'); field.textContent = key;
        const input = document.createElement('input'); input.type = 'text'; input.inputMode = 'decimal';
        input.placeholder = 'm:ss.mmm'; input.dataset.index = wordIndex; input.dataset.key = key;
        input.value = stamp(Number(word[key]));
        input.onchange = () => {
          const value = parseStamp(input.value);
          const other = Number(word[key === 'start' ? 'end' : 'start']);
          const valid = Number.isFinite(value) && value >= 0 && value <= data.duration
            && (key === 'start' ? value < other : value > other);
          if (!valid) { input.value = stamp(Number(word[key])); find('timelineStatus').textContent = 'Use m:ss.mmm, with the start before the end.'; return; }
          const before = snapshot([words.find(entry => entry.word === word)]);
          word[key] = round(value); input.value = stamp(word[key]);
          record(before);
        };
        field.append(input); row.append(field);
      }
      list.append(row);
    });
    if (moveView) fitLine(index);
    renderLines();
    find('timelineLines').querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
  }

  async function save() {
    if (!data || !jobId) return false;
    const status = find('timelineStatus'); status.textContent = 'Saving…';
    try {
      await api(`/api/jobs/${jobId}/timings`, { timings: data.timings });
      saved = cursor; changed = false; data.needs_render = true;
      status.textContent = 'Saved. Rebuild the video to apply.';
      return true;
    } catch (error) { status.textContent = error.message; return false; }
  }

  openButton.onclick = async () => {
    if (!jobId) { toast('Choose a song first, then open its word timeline.'); return; }
    try {
      data = await api(`/api/jobs/${jobId}/timeline`);
      openedJob = jobId; selectedLine = 0; changed = false; history = []; cursor = saved = 0;
      find('timelineUnsaved').hidden = true;
      words = data.timings.flatMap((line, lineIndex) => line.words.map(word => ({ word, line: lineIndex })));
      words.forEach((entry, flat) => { entry.flat = flat; });
      tracks.replaceChildren();
      for (const name of ['vocals', 'drums', 'bass', 'other']) {
        if (!data.stems[name]) continue;
        const row = document.createElement('div'); row.className = 'timeline-track'; row.dataset.stem = name;
        const label = document.createElement('span'); label.textContent = name;
        const canvas = document.createElement('canvas');
        attach(canvas);
        row.append(label, canvas); tracks.append(row);
      }
      if (!tracks.children.length) tracks.textContent = 'Stem graphs are unavailable for this job.';
      audio.src = data.audio;
      find('timelineStatus').textContent = data.needs_render ? 'Saved timing changes need a video rebuild.' : '';
      dialog.showModal(); setView(0, Math.min(24, data.duration)); selectLine(0); draw();
    } catch (error) { toast("Can't open the word timeline. " + error.message); }
  };
  const editTimings = document.getElementById('editTimings');
  if (editTimings) editTimings.onclick = () => openButton.click();
  const askToClose = () => {
    if (!changed) { dialog.close(); return; }
    find('timelineUnsaved').hidden = false; find('timelineKeep').focus();
  };
  find('closeTimeline').onclick = askToClose;
  dialog.addEventListener('cancel', event => { if (changed) { event.preventDefault(); askToClose(); } });
  find('timelineKeep').onclick = () => { find('timelineUnsaved').hidden = true; };
  find('timelineDiscard').onclick = () => {
    while (cursor > 0) { cursor--; for (const change of history[cursor]) Object.assign(words[change.flat].word, change.before); }
    history = []; cursor = saved = 0; changed = false;
    find('timelineUnsaved').hidden = true; dialog.close();
  };
  find('timelineSaveClose').onclick = async () => { if (await save()) { find('timelineUnsaved').hidden = true; dialog.close(); } };
  dialog.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || event.target.matches('input, textarea')) return;
    const key = event.key.toLowerCase();
    if (key === 'z' || key === 'y') { event.preventDefault(); step(key === 'y' || event.shiftKey ? 1 : -1); }
  });
  dialog.addEventListener('close', () => { audio.pause(); cancelAnimationFrame(frame); });
  position.oninput = () => setView(Number(position.value), span);
  find('timelineZoomIn').onclick = () => zoomAround(begin + span / 2, 1 / 1.6);
  find('timelineZoomOut').onclick = () => zoomAround(begin + span / 2, 1.6);
  find('timelineFitLine').onclick = () => fitLine(selectedLine);
  find('timelineWhole').onclick = () => setView(0, data.duration);
  find('saveTimeline').onclick = save;
  find('rerenderTimeline').onclick = async () => {
    if (changed && !(await save())) return;
    if (!openedJob || openedJob !== jobId) return;
    audio.pause(); dialog.close();
    await action('rerender', {});
  };
  const previousRenderGallery = renderGallery;
  renderGallery = function (snapshot) {
    previousRenderGallery(snapshot);
    for (const index of snapshot.dirty || []) {
      const card = document.querySelector(`[data-image-index="${index}"]`);
      const selectedButton = card?.querySelector('.card-actions button');
      if (selectedButton?.disabled && selectedButton.textContent === 'Selected image') {
        selectedButton.textContent = 'Selected · rebuild needed';
        selectedButton.title = 'This candidate is selected. Rebuild the video to see it in the export.';
      }
    }
  };
})();
