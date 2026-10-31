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
      <p class="help">Click a line to inspect its words. Click a waveform to seek the song.</p></div>
      <button type="button" id="closeTimeline">Close</button></div>
    <audio id="timelineAudio" controls preload="metadata"></audio>
    <div class="timeline-tools"><label>Window <select id="timelineZoom"><option value="12">12 seconds</option>
      <option value="24" selected>24 seconds</option><option value="48">48 seconds</option>
      <option value="all">Whole song</option></select></label>
      <label>Position <input id="timelinePosition" type="range" min="0" value="0" step="0.1"></label>
      <span id="timelineRange"></span></div>
    <div id="timelineTracks" class="timeline-tracks"></div>
    <div class="timeline-edit"><div id="timelineLines" class="timeline-lines"></div>
      <div class="timeline-word-panel"><h3 id="timelineLineTitle">Choose a lyric line</h3>
      <div id="timelineWords" class="timeline-words"></div><div class="row timeline-actions">
      <button type="button" id="saveTimeline" class="primary">Save timings</button>
      <button type="button" id="rerenderTimeline">Rebuild video</button>
      <span id="timelineStatus" role="status"></span></div></div></div>`;
  document.body.append(dialog);
  const find = id => dialog.querySelector('#' + id);
  const audio = find('timelineAudio');
  const tracks = find('timelineTracks');
  const position = find('timelinePosition');
  const zoom = find('timelineZoom');
  let data = null, selectedLine = 0, changed = false, frame = 0, openedJob = '';
  const stamp = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  const lineStart = line => Number(line.words[0].start);
  const lineEnd = line => Number(line.words.at(-1).end);
  const windowSize = () => zoom.value === 'all' ? data.duration : Math.min(data.duration, Number(zoom.value));
  const windowStart = () => Math.min(Number(position.value), Math.max(0, data.duration - windowSize()));

  function updateWindow() {
    if (!data) return;
    position.max = String(Math.max(0, data.duration - windowSize()));
    position.value = String(Math.min(Number(position.value), Number(position.max)));
    find('timelineRange').textContent = `${stamp(windowStart())} – ${stamp(windowStart() + windowSize())}`;
    draw();
  }

  function draw() {
    if (!data || !dialog.open) return;
    cancelAnimationFrame(frame);
    const begin = windowStart(), span = windowSize();
    const selected = data.timings[selectedLine];
    for (const row of tracks.querySelectorAll('.timeline-track')) {
      const canvas = row.querySelector('canvas');
      const context = canvas.getContext('2d');
      const peaks = data.stems[row.dataset.stem].peaks;
      const width = canvas.width, height = canvas.height;
      context.fillStyle = '#111a19'; context.fillRect(0, 0, width, height);
      const left = Math.max(0, (lineStart(selected) - begin) / span * width);
      const right = Math.min(width, (lineEnd(selected) - begin) / span * width);
      if (right > left) { context.fillStyle = '#d5f59b1c'; context.fillRect(left, 0, right - left, height); }
      context.fillStyle = row.dataset.stem === 'vocals' ? '#d5f59b' : '#70b8d2';
      const first = Math.max(0, Math.floor(begin / data.duration * peaks.length));
      const last = Math.min(peaks.length, Math.ceil((begin + span) / data.duration * peaks.length));
      for (let i = first; i < last; i++) {
        const x = (i / peaks.length * data.duration - begin) / span * width;
        const level = Math.min(1, peaks[i] * 2.1);
        context.fillRect(x, height * (1 - level) / 2, Math.max(1, width / peaks.length * data.duration / span), Math.max(1, height * level));
      }
      const cursor = (audio.currentTime - begin) / span * width;
      if (cursor >= 0 && cursor <= width) { context.fillStyle = '#ffbd76'; context.fillRect(cursor, 0, 2, height); }
    }
    frame = requestAnimationFrame(draw);
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

  function selectLine(index) {
    selectedLine = index;
    const line = data.timings[index];
    find('timelineLineTitle').textContent = `Line ${index + 1}: ${line.text}`;
    const words = find('timelineWords'); words.replaceChildren();
    for (const word of line.words) {
      const row = document.createElement('div'); row.className = 'timeline-word';
      const label = document.createElement('strong'); label.textContent = word.text;
      row.append(label);
      for (const key of ['start', 'end']) {
        const field = document.createElement('label'); field.textContent = key;
        const input = document.createElement('input'); input.type = 'number'; input.min = '0';
        input.max = String(data.duration); input.step = '0.01'; input.value = Number(word[key]).toFixed(2);
        input.onchange = () => {
          const value = Number(input.value);
          if (!Number.isFinite(value) || value < 0 || value > data.duration) { input.value = Number(word[key]).toFixed(2); return; }
          word[key] = value; changed = true;
          find('timelineStatus').textContent = 'Unsaved timing changes';
          renderLines();
        };
        field.append(input); row.append(field);
      }
      words.append(row);
    }
    position.value = String(Math.max(0, Math.min(Number(position.max), lineStart(line) - 2)));
    updateWindow(); renderLines();
    find('timelineLines').querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
  }

  async function save() {
    if (!data || !jobId) return false;
    const status = find('timelineStatus'); status.textContent = 'Saving…';
    try {
      await api(`/api/jobs/${jobId}/timings`, { timings: data.timings });
      changed = false; data.needs_render = true;
      status.textContent = 'Saved. Rebuild the video to apply.';
      return true;
    } catch (error) { status.textContent = error.message; return false; }
  }

  openButton.onclick = async () => {
    if (!jobId) { toast('Choose a song first, then open its word timeline.'); return; }
    try {
      data = await api(`/api/jobs/${jobId}/timeline`);
      openedJob = jobId; selectedLine = 0; changed = false;
      tracks.replaceChildren();
      for (const name of ['vocals', 'drums', 'bass', 'other']) {
        if (!data.stems[name]) continue;
        const row = document.createElement('div'); row.className = 'timeline-track'; row.dataset.stem = name;
        const label = document.createElement('span'); label.textContent = name;
        const canvas = document.createElement('canvas'); canvas.width = 1200; canvas.height = 68;
        canvas.onclick = event => { audio.currentTime = windowStart() + event.offsetX / canvas.clientWidth * windowSize(); draw(); };
        row.append(label, canvas); tracks.append(row);
      }
      if (!tracks.children.length) tracks.textContent = 'Stem graphs are unavailable for this job.';
      audio.src = data.audio;
      find('timelineStatus').textContent = data.needs_render ? 'Saved timing changes need a video rebuild.' : '';
      dialog.showModal(); updateWindow(); selectLine(0);
    } catch (error) { toast("Can't open the word timeline. " + error.message); }
  };
  const editTimings = document.getElementById('editTimings');
  if (editTimings) editTimings.onclick = () => openButton.click();
  find('closeTimeline').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { audio.pause(); cancelAnimationFrame(frame); });
  position.oninput = updateWindow; zoom.onchange = updateWindow;
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
