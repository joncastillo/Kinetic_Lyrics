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
      <button type="button" id="timelineExport" title="Download every word's start and end as a JSON file">Export JSON</button>
      <button type="button" id="timelineImport" title="Load word timings from a JSON file exported here">Import JSON</button>
      <input type="file" id="timelineImportFile" accept="application/json,.json" hidden>
      <label>Position <input id="timelinePosition" type="range" min="0" value="0" step="0.001"></label>
      <span id="timelineRange"></span></div>
    <div id="timelineTracks" class="timeline-tracks"></div>
    <div id="timelineClip" class="timeline-clip" hidden><video id="timelineClipVideo" muted playsinline preload="auto"></video>
      <span id="timelineClipLabel"></span></div>
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
    changed = cursor !== saved || !!data.draft;
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
      if (row.dataset.lane === 'artwork') { drawArtwork(canvas, ratio); continue; }
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

  // The artwork lane: where each background and video clip plays. A clip runs from its slot's start and is cut
  // off when the next background takes over; dragging it slides the clip under that window to pick its start frame.
  function drawArtwork(canvas, ratio) {
    const cssWidth = canvas.clientWidth, cssHeight = canvas.clientHeight;
    if (canvas.width !== Math.round(cssWidth * ratio) || canvas.height !== Math.round(cssHeight * ratio)) {
      canvas.width = Math.round(cssWidth * ratio); canvas.height = Math.round(cssHeight * ratio);
    }
    const context = canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const width = cssWidth, height = cssHeight, x = t => (t - begin) / span * width;
    context.fillStyle = '#111a19'; context.fillRect(0, 0, width, height);
    context.font = '11px "Segoe UI", sans-serif'; context.textBaseline = 'top';
    for (const lane of data.artwork) {
      if (lane.end < begin || lane.start > begin + span) continue;
      const left = x(lane.start), right = x(lane.end), active = artDrag?.lane === lane;
      if (lane.video && lane.length) {  // the whole clip, faint where the window cuts it off
        const clipLeft = x(lane.start - lane.offset), clipRight = x(lane.start - lane.offset + lane.length);
        context.fillStyle = 'rgba(229,155,255,.13)'; context.fillRect(clipLeft, height * .72, clipRight - clipLeft, height * .2);
        context.fillStyle = 'rgba(229,155,255,.35)';
        for (let frame = clipLeft; frame < clipRight; frame += 9) context.fillRect(frame, height * .74, 3, height * .16);
      }
      context.save(); context.beginPath(); context.rect(left, 0, right - left, height); context.clip();
      context.fillStyle = lane.video ? 'rgba(229,155,255,.22)' : 'rgba(118,214,255,.14)';
      context.fillRect(left, 0, right - left, height);
      const poster = lane.poster;
      if (poster?.complete && poster.naturalWidth) {
        const thumb = height * .66, wide = thumb * poster.naturalWidth / poster.naturalHeight;
        context.globalAlpha = .85; context.drawImage(poster, left + 4, 4, wide, thumb); context.globalAlpha = 1;
      }
      context.fillStyle = lane.video ? '#f1d4ff' : '#cdeffb';
      const name = (lane.video ? `Video ${lane.index + 1} · from ${stamp(lane.offset)}` : `Image ${lane.index + 1}`);
      context.fillText(name, left + 6 + height * .66 * 1.78, 6);
      if (lane.video) { context.fillStyle = 'rgba(241,212,255,.75)'; context.fillText('drag: start frame · double-click: zoom, move, crop', left + 6 + height * .66 * 1.78, 22); }
      context.restore();
      context.fillStyle = active ? '#ffbd76' : 'rgba(255,255,255,.55)';
      context.fillRect(left, 0, active ? 2 : 1, height);
    }
    const cursor = x(audio.currentTime);
    if (cursor >= 0 && cursor <= width) { context.fillStyle = '#ffbd76'; context.fillRect(cursor - 1, 0, 2, height); }
  }


  // ---- Video framing: double-click a clip in the artwork lane to zoom, move and crop it in the frame. The drawing
  // here uses the renderer's arithmetic (video_art.frame_picture), with white wherever the clip does not reach.
  const framingDialog = document.createElement('dialog');
  framingDialog.className = 'framing-dialog';
  framingDialog.innerHTML = `
    <div class="timeline-heading"><div><div class="eyebrow">Video clip</div><h2 id="framingTitle">Frame the video</h2>
      <p class="help">Drag the picture to move it and use the mouse wheel or Zoom to resize it. Zoom 100% fills the
      frame; smaller leaves white around it. Crop trims the clip's own edges first.</p></div>
      <button type="button" id="framingClose">Close</button></div>
    <canvas id="framingCanvas"></canvas>
    <video id="framingVideo" muted playsinline loop preload="auto" hidden></video>
    <div class="framing-controls">
      <label>Zoom <output id="framingZoomOut"></output><input id="framingZoom" type="range" min="-2.3" max="1.79" step=".01"></label>
      <label>Crop left <output data-out="left"></output><input data-crop="left" type="range" min="0" max=".45" step=".005"></label>
      <label>Crop right <output data-out="right"></output><input data-crop="right" type="range" min="0" max=".45" step=".005"></label>
      <label>Crop top <output data-out="top"></output><input data-crop="top" type="range" min="0" max=".45" step=".005"></label>
      <label>Crop bottom <output data-out="bottom"></output><input data-crop="bottom" type="range" min="0" max=".45" step=".005"></label>
    </div>
    <div class="row timeline-actions">
      <button type="button" id="framingFill">Fill frame</button>
      <button type="button" id="framingWhole">Show whole video</button>
      <button type="button" id="framingCenter">Centre</button>
      <button type="button" id="framingReset">Reset</button>
      <button type="button" id="framingPlay">Play</button>
      <button type="button" id="framingSave" class="primary">Save framing</button>
      <span id="framingStatus" role="status"></span></div>`;
  document.body.append(framingDialog);
  const fpick = id => framingDialog.querySelector('#' + id);
  const DEFAULT_FRAMING = { zoom: 1, x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0 };
  let framingLane = null, framing = null, framingLoop = 0, framingDrag = null;

  function framingGeometry(W, H) {
    const video = fpick('framingVideo'), w0 = video.videoWidth || 16, h0 = video.videoHeight || 9;
    const sx = w0 * framing.left, sy = h0 * framing.top;
    const sw = Math.max(1, w0 * (1 - framing.left - framing.right)), sh = Math.max(1, h0 * (1 - framing.top - framing.bottom));
    const scale = Math.max(W / sw, H / sh) * framing.zoom;
    const dw = sw * scale, dh = sh * scale;
    return { sx, sy, sw, sh, dw, dh, dx: (W - dw) / 2 + framing.x * W, dy: (H - dh) / 2 + framing.y * H, w0, h0 };
  }
  function drawFraming() {
    if (!framingDialog.open) return;
    const canvas = fpick('framingCanvas'), video = fpick('framingVideo');
    const W = data.frame?.width || 1920, H = data.frame?.height || 1080;
    const shown = Math.min(840, framingDialog.clientWidth - 40);
    const ratio = window.devicePixelRatio || 1;
    canvas.style.width = shown + 'px'; canvas.style.height = shown * H / W + 'px';
    canvas.width = Math.round(shown * ratio); canvas.height = Math.round(shown * H / W * ratio);
    const context = canvas.getContext('2d'), k = canvas.width / W;
    context.setTransform(k, 0, 0, k, 0, 0);
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, W, H);
    if (video.readyState >= 2) {
      const g = framingGeometry(W, H);
      context.drawImage(video, g.sx, g.sy, g.sw, g.sh, g.dx, g.dy, g.dw, g.dh);
    }
    framingLoop = requestAnimationFrame(drawFraming);
  }
  function syncFramingControls() {
    fpick('framingZoom').value = Math.log(framing.zoom);
    fpick('framingZoomOut').textContent = Math.round(framing.zoom * 100) + '%';
    for (const input of framingDialog.querySelectorAll('[data-crop]')) {
      input.value = framing[input.dataset.crop];
      framingDialog.querySelector(`[data-out="${input.dataset.crop}"]`).textContent = Math.round(framing[input.dataset.crop] * 100) + '%';
    }
  }
  function openFraming(lane) {
    framingLane = lane;
    framing = { ...DEFAULT_FRAMING, ...(lane.framing || {}) };
    fpick('framingTitle').textContent = `Frame video ${lane.index + 1}`;
    fpick('framingStatus').textContent = '';
    const video = fpick('framingVideo');
    video.src = lane.video; video.pause(); fpick('framingPlay').textContent = 'Play';
    video.addEventListener('loadedmetadata', () => { try { video.currentTime = lane.offset || 0; } catch {} }, { once: true });
    syncFramingControls();
    framingDialog.showModal();
    cancelAnimationFrame(framingLoop); drawFraming();
  }
  fpick('framingZoom').oninput = event => { framing.zoom = Math.exp(Number(event.target.value)); syncFramingControls(); };
  for (const input of framingDialog.querySelectorAll('[data-crop]'))
    input.oninput = () => { framing[input.dataset.crop] = Number(input.value); syncFramingControls(); };
  fpick('framingFill').onclick = () => { framing.zoom = 1; framing.x = framing.y = 0; syncFramingControls(); };
  fpick('framingWhole').onclick = () => {
    const W = data.frame?.width || 1920, H = data.frame?.height || 1080, g = framingGeometry(W, H);
    framing.zoom = Math.min(W / g.sw, H / g.sh) / Math.max(W / g.sw, H / g.sh); framing.x = framing.y = 0; syncFramingControls();
  };
  fpick('framingCenter').onclick = () => { framing.x = framing.y = 0; };
  fpick('framingReset').onclick = () => { framing = { ...DEFAULT_FRAMING }; syncFramingControls(); };
  fpick('framingPlay').onclick = () => {
    const video = fpick('framingVideo');
    if (video.paused) { video.play(); fpick('framingPlay').textContent = 'Pause'; }
    else { video.pause(); fpick('framingPlay').textContent = 'Play'; }
  };
  const closeFraming = () => { fpick('framingVideo').pause(); cancelAnimationFrame(framingLoop); framingDialog.close(); };
  fpick('framingClose').onclick = closeFraming;
  fpick('framingSave').onclick = async () => {
    const lane = framingLane, saved = { ...framing };
    try {
      await api(`/api/jobs/${openedJob}/clip-start`, { index: lane.index, framing: saved });
      lane.framing = saved; closeFraming();
      find('timelineStatus').textContent = `Video ${lane.index + 1} framing saved. Rebuild changed images to apply.`;
    } catch (error) { fpick('framingStatus').textContent = error.message; }
  };
  const framingCanvas = fpick('framingCanvas');
  framingCanvas.addEventListener('pointerdown', event => {
    framingCanvas.setPointerCapture(event.pointerId);
    framingDrag = { x: event.offsetX, y: event.offsetY, start: { x: framing.x, y: framing.y } };
  });
  framingCanvas.addEventListener('pointermove', event => {
    if (!framingDrag) return;
    framing.x = Math.max(-1.5, Math.min(1.5, framingDrag.start.x + (event.offsetX - framingDrag.x) / framingCanvas.clientWidth));
    framing.y = Math.max(-1.5, Math.min(1.5, framingDrag.start.y + (event.offsetY - framingDrag.y) / framingCanvas.clientHeight));
  });
  framingCanvas.addEventListener('pointerup', () => { framingDrag = null; });
  framingCanvas.addEventListener('wheel', event => {
    event.preventDefault();
    framing.zoom = Math.max(.1, Math.min(6, framing.zoom * Math.exp(-event.deltaY * .0015)));
    syncFramingControls();
  }, { passive: false });

  let artDrag = null;
  const laneAt = (canvas, offsetX) => {
    const t = begin + offsetX / canvas.clientWidth * span;
    return data.artwork.find(lane => lane.start <= t && t < lane.end) || null;
  };
  function showClip(lane) {
    const box = find('timelineClip'), video = find('timelineClipVideo');
    if (!lane?.video) { box.hidden = true; return; }
    box.hidden = false;
    if (video.dataset.src !== lane.video) { video.src = lane.video; video.dataset.src = lane.video; }
    const seek = () => { try { video.currentTime = Math.min(lane.offset, Math.max(0, lane.length - .04)); } catch {} };
    if (video.readyState >= 1) seek(); else video.addEventListener('loadedmetadata', seek, { once: true });
    find('timelineClipLabel').textContent = `Video ${lane.index + 1} starts ${stamp(lane.offset)} into the clip and plays for `
      + `${(lane.end - lane.start).toFixed(1)} s, until the next background.`;
  }
  async function saveClipStart(lane, previous) {
    const status = find('timelineStatus');
    try {
      await api(`/api/jobs/${openedJob}/clip-start`, { index: lane.index, offset: lane.offset });
      status.textContent = `Video ${lane.index + 1} now starts ${stamp(lane.offset)} into the clip. Rebuild changed images to apply.`;
    } catch (error) { lane.offset = previous; showClip(lane); status.textContent = error.message; }
  }
  function attachArtwork(canvas) {
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      canvas.setPointerCapture(event.pointerId);
      const lane = laneAt(canvas, event.offsetX);
      artDrag = lane?.video ? { lane, x: event.offsetX, offset: lane.offset, moved: false }
                            : { pan: true, x: event.offsetX, viewBegin: begin, moved: false };
      if (lane?.video) showClip(lane);
    });
    canvas.addEventListener('pointermove', event => {
      if (!artDrag) { canvas.style.cursor = laneAt(canvas, event.offsetX)?.video ? 'ew-resize' : 'grab'; return; }
      const dx = event.offsetX - artDrag.x;
      if (Math.abs(dx) > 3) artDrag.moved = true;
      if (!artDrag.moved) return;
      const seconds = dx / canvas.clientWidth * span;
      if (artDrag.pan) { setView(artDrag.viewBegin - seconds, span); return; }
      // Dragging the clip right shows earlier frames when its slot starts; left shows later ones.
      const lane = artDrag.lane, latest = Math.max(0, lane.length - .04);
      lane.offset = Math.round(Math.min(latest, Math.max(0, artDrag.offset - seconds)) * 1000) / 1000;
      showClip(lane);
    });
    const finish = event => {
      if (!artDrag) return;
      const drag = artDrag; artDrag = null;
      if (drag.lane && drag.moved && drag.lane.offset !== drag.offset) saveClipStart(drag.lane, drag.offset);
      else if (!drag.moved) audio.currentTime = begin + event.offsetX / canvas.clientWidth * span;
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', () => { if (artDrag?.lane) artDrag.lane.offset = artDrag.offset; artDrag = null; });
    canvas.addEventListener('dblclick', event => {
      const lane = laneAt(canvas, event.offsetX);
      if (lane?.video) openFraming(lane);
    });
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      const fraction = event.offsetX / canvas.clientWidth;
      if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) setView(begin + (event.deltaX || event.deltaY) / canvas.clientWidth * span, span);
      else zoomAround(begin + fraction * span, Math.exp(event.deltaY * .0015), fraction);
    }, { passive: false });
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
      status.textContent = 'Saving… a video being made is stopped and restarted with these timings.';
      const result = await api(`/api/jobs/${jobId}/timings`, { timings: data.timings }, 120000);
      saved = cursor; changed = false; data.needs_render = !result?.restarted && !result?.draft;
      if (result?.draft) data.draft = false;
      status.textContent = result?.draft ? 'Saved. Restart from Step 2: Prompts to continue the song with these timings.'
                         : result?.restarted ? 'Saved. The video was stopped and is being made again with these timings.'
                                             : 'Saved. Rebuild the video to apply.';
      if (result?.restarted && typeof poll === 'function') poll();
      return result?.draft ? 'draft' : result?.restarted ? 'restarted' : true;
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
      find('timelineClip').hidden = true;
      if (data.artwork?.length) {
        const row = document.createElement('div'); row.className = 'timeline-track timeline-artwork'; row.dataset.lane = 'artwork';
        const label = document.createElement('span'); label.textContent = 'artwork';
        const canvas = document.createElement('canvas');
        attachArtwork(canvas);
        row.append(label, canvas); tracks.append(row);
        for (const lane of data.artwork) { lane.poster = new Image(); lane.poster.src = lane.image; }
      }
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
      find('timelineStatus').textContent = data.draft
        ? 'Step 1: Timing did not finish, so these are draft timings spread evenly over the song. Drag each line onto the vocals, then Save.'
        : data.needs_render ? 'Saved timing changes need a video rebuild.' : '';
      if (data.draft) changed = true;  // a draft is unsaved work until the user saves it
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

  // Timings as a JSON file: the same lines and words with their start and end in seconds.
  find('timelineExport').onclick = () => {
    if (!data) return;
    const payload = {
      format: 'kinetic-lyrics-timings', version: 1, job: openedJob, exported: new Date().toISOString(),
      timings: data.timings.map(line => ({
        text: line.text,
        words: line.words.map(word => ({ text: word.text, start: Number(word.start), end: Number(word.end) }))
      }))
    };
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
    link.download = `${openedJob || 'song'}-timings.json`;
    link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    find('timelineStatus').textContent = 'Timings exported as JSON.' + (changed ? ' The file includes your unsaved changes.' : '');
  };
  find('timelineImport').onclick = () => find('timelineImportFile').click();
  find('timelineImportFile').onchange = async () => {
    const input = find('timelineImportFile'), file = input.files[0]; input.value = '';
    if (!file || !data) return;
    const status = find('timelineStatus');
    try {
      let parsed;
      try { parsed = JSON.parse(await file.text()); } catch { throw Error('the file is not valid JSON'); }
      const lines = Array.isArray(parsed) ? parsed : parsed?.timings;
      if (!Array.isArray(lines)) throw Error('the file has no timings list');
      if (lines.length !== data.timings.length) throw Error(`it has ${lines.length} lines; this song has ${data.timings.length}`);
      data.timings.forEach((line, i) => {
        const other = lines[i]?.words;
        if (!Array.isArray(other) || other.length !== line.words.length) throw Error(`line ${i + 1} has a different number of words`);
        line.words.forEach((word, j) => {
          const start = Number(other[j]?.start), end = Number(other[j]?.end);
          if (String(other[j]?.text ?? word.text) !== word.text) throw Error(`line ${i + 1}, word ${j + 1} is "${other[j].text}", expected "${word.text}"`);
          if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || end > data.duration + .05)
            throw Error(`line ${i + 1}, word ${j + 1} ("${word.text}") has an invalid start or end`);
        });
      });
      // One undo step for the whole import.
      const before = snapshot(words);
      data.timings.forEach((line, i) => line.words.forEach((word, j) => {
        word.start = round(Number(lines[i].words[j].start));
        word.end = round(Math.min(data.duration, Number(lines[i].words[j].end)));
      }));
      record(before);
      refreshWordInputs();
      status.textContent = cursor !== saved
        ? `Imported timings from ${file.name}. Save timings to keep them, or Ctrl+Z to undo.`
        : `${file.name} matches the current timings; nothing changed.`;
    } catch (error) {
      status.textContent = `Could not import ${file.name}: ${error.message}.`;
    }
  };
  find('rerenderTimeline').onclick = async () => {
    const result = changed ? await save() : true;
    if (!result || result === 'draft') return;  // no video yet: the song continues from Step 2 instead
    if (!openedJob || openedJob !== jobId) return;
    audio.pause(); dialog.close();
    if (result !== 'restarted') await action('rerender', {});
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
