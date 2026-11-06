/* Storyline panel: for every segment of the song, the image prompt and the timed story the video follows
   (characters, environment, camera, and beats of action), editable, importable and exportable. */
function setupStoryline() {
  const head = [...document.querySelectorAll('.panel-head')].find(h => /Illustration workspace/.test(h.textContent));
  if (!head) return;
  const open = document.createElement('button');
  open.type = 'button'; open.id = 'openStoryline'; open.textContent = 'Storyline';
  open.title = 'Image prompts and the timed storyline every segment follows';
  head.insertBefore(open, head.querySelector('.badge'));
  // In-scene lyric spots are found automatically once the AI video clips are made (see queue_effects_after_animation).

  const dialog = document.createElement('dialog');
  dialog.className = 'modal storyline-modal';
  document.body.append(dialog);
  const esc = value => String(value ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const clock = s => s == null ? '?' : `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
  let data = null, edited = false;

  open.onclick = () => { if (!jobId) { toast?.('Open a song first.'); return; } load(); };

  async function load() {
    dialog.innerHTML = '<p class="help">Loading the storyline…</p>';
    if (!dialog.open) dialog.showModal();
    try { data = await api(`/api/jobs/${jobId}/story`); }
    catch (error) { dialog.innerHTML = `<p class="help">${esc(error.message)}</p><button type="button" class="story-close">Close</button>`;
                    dialog.querySelector('.story-close').onclick = () => dialog.close(); return; }
    const message = data.error || (data.regenerating ? 'This song is being regenerated from before the storyline: the previous storyline is gone, and the new one appears here once the new prompts are written.' : '');
    if (message) { dialog.innerHTML = `<p class="help">${esc(message)}</p><button type="button" class="story-close">Close</button>`;
                   dialog.querySelector('.story-close').onclick = () => dialog.close(); return; }
    for(const segment of data.segments||[]){const story=segment.story;if(!story||!segment.section)continue;const seconds=+(segment.section[1]-segment.section[0]).toFixed(3),old=story.seconds||seconds;if(seconds>0){for(const beat of story.beats||[]){beat.start=+(beat.start*seconds/old).toFixed(3);beat.end=+(beat.end*seconds/old).toFixed(3)}story.seconds=seconds;if(story.beats?.length)story.beats.at(-1).end=seconds;}}
    edited = false; render();
  }

  function render() {
    const needsStory = data.video;
    dialog.innerHTML = `
      <div class="story-head"><div><div class="eyebrow">Prompt generator</div><h2>Storyline</h2>
        <p class="help">Every segment's image prompt, and the story its video clip follows: who is in it, where it
        happens, how the camera moves, and timed beats of what happens (seconds from the start of the clip). Written by
        the AI before the images; edit anything at any time. Saving applies to clips not made yet; Regenerate makes
        every image and clip again from these prompts and this storyline. Art Style comes from Reference image prompt; the AI constructs Characters, Environment, Camera and Scene. Scene direction in Project settings chooses timed actions or a scene summary when writing with AI.</p></div>
        <div class="row story-tools">
          <button type="button" data-act="import">Import JSON</button><input type="file" accept="application/json,.json" hidden>
          <button type="button" data-act="export">Export JSON</button>
          ${needsStory ? '<button type="button" data-act="write" title="The director model writes the storyline again from the image prompts and lyrics (a queued job)">Write with AI</button>' : ''}
          <button type="button" data-act="close">Close</button></div></div>
      <div class="story-refs">${refsHtml()}</div>
      ${data.has_story ? entitiesHtml() : ''}
      ${needsStory && !data.has_story ? '<p class="story-banner">This song has no storyline yet. Use <b>Write with AI</b>, or fill it in yourself.</p>' : ''}
      <div class="story-segments">${data.segments.map(segmentHtml).join('')}</div>
      <div class="story-footer"><span class="story-status help" role="status"></span>
        <button type="button" data-act="save" class="primary">Save</button>
        <button type="button" data-act="regenerate">Regenerate images & videos…</button>
        <button type="button" data-act="close">Close</button></div>
      <p class="tag-warning story-tag-warning" role="alert" hidden></p>
      <div class="story-warning" hidden role="alertdialog" aria-label="Discard generated images and videos">
        <p><b>Every generated image and video clip of this song will be discarded</b> (moved aside, not deleted) and made
        again from these prompts and this storyline. ${data.busy ? 'The work running now is stopped first. ' : ''}This takes
        as long as the original images and clips did.</p>
        <div class="row"><button type="button" data-act="cancel-regenerate">Keep them</button>
        <button type="button" data-act="confirm-regenerate" class="danger">Discard and regenerate</button></div></div>`;
    wire();
  }

  function refsHtml() {
    const change = '<button type="button" data-act="project-refs" class="small">Change in Project tab</button>';
    if (!data.references.length) return '<span class="help">No reference images.</span> ' + change;
    const role = data.reference_use === 'likeness'
      ? `Cast as the main character${data.main_character ? `: ${esc(data.main_character)}` : ''}.`
      : 'Style references: they guide the painting technique.';
    return `<div class="story-ref-images">${data.references.map(u => `<img src="${esc(u)}" alt="Reference image">`).join('')}</div>
      <p class="help">${role} Image models that take references receive these images; the video model receives the
      main character's description in every part (it cannot take a reference image). Regenerate after changing them.</p>${change}`;
  }

  // A recurring character, object or place: its painted reference picture (made with the images) and its looks.
  // The cast's sheet is painted from one of the project's photos; the scenes get that photo, so it goes by the
  // photo's tag, and until its sheet is painted the photo stands for it.
  const castPhoto = e => {
    const photos = state?.render_settings?.references || [];
    const number = +(String(e.photo || '').match(/^photo(\d+)$/i)?.[1] || 1);  // the picture the story's tag names
    const url = photos[number - 1] || photos[0] || '';
    return { url, tag: '@photo' + (Math.max(0, photos.indexOf(url)) + 1) };
  };
  const tagLabel = tag => `<small class="ref-tag" data-tag="${esc(tag)}" title="${esc(tag)} · click to copy">${esc(tag)}</small>`;
  const entityHtml = e => {
    const picture = e.image || (e.cast ? castPhoto(e).url : '');
    return `<span class="story-ref story-entity" title="${esc(e.name)}">${picture
      ? `<img src="${esc(picture)}" alt="${esc(e.name)}">` : ''}<span>${esc(e.name)}${picture ? '' : ' (no picture yet)'}</span>${picture ? tagLabel(e.cast ? castPhoto(e).tag : referenceTag(e.name)) : ''}</span>`;
  };

  // ---- References editor: the recurring characters, objects and places, each with its picture, label and the
  // images it appears in. Each card saves on its own (it is not part of the storyline's Save).
  const ranges = numbers => {
    const list = [...new Set(numbers)].sort((a, b) => a - b), parts = [];
    for (let k = 0; k < list.length; k++) { let end = k; while (end + 1 < list.length && list[end + 1] === list[end] + 1) end++;
      parts.push(end > k ? `${list[k]}-${list[end]}` : String(list[k])); k = end; }
    return parts.join(', ');
  };
  const parseImages = text => String(text || '').split(/[,\s]+/).filter(Boolean).flatMap(part => {
    const m = part.match(/^(\d+)(?:-(\d+))?$/); if (!m) throw Error(`"${part}" is not an image number or range`);
    const a = +m[1], b = m[2] ? +m[2] : a; return Array.from({ length: Math.max(0, b - a + 1) }, (_, i) => a + i); });
  function entityCard(e) {
    const isNew = !e, x = e || { name: '', kind: 'character', looks: '', segments: [], cast: false, base: '' };
    const photo = x.image ? { url: x.image, tag: x.cast ? castPhoto(x).tag : referenceTag(x.name) } : x.cast ? castPhoto(x) : null;
    const picture = photo?.url ? `<div class="story-entity-photo"><img class="story-entity-pic" src="${esc(photo.url)}" alt="${esc(x.name)}"><small class="ref-tag" data-tag="${esc(photo.tag)}" title="${esc(photo.tag)} · click to copy">${esc(photo.tag)}</small></div>`
      : x.cast ? '<div class="story-entity-pic blank">Add a project photo</div>'
      : x.kind === 'place' ? '<div class="story-entity-pic blank">No picture yet</div>'
      : `<div class="story-entity-pic blank">${isNew ? 'New reference' : 'Painted with the next image that shows it'}</div>`;
    return `<div class="story-entity-card" data-id="${esc(x.id || '')}">${picture}
      <div class="story-entity-fields">
        <div class="row"><input data-e="name" value="${esc(x.name)}" placeholder="Name, e.g. the koala" aria-label="Name">
          <select data-e="kind" aria-label="Kind">${['character', 'object', 'place'].map(k => `<option${k === x.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
        <textarea data-e="looks" rows="2"${isNew ? '' : ' hidden'} placeholder="How it looks, so it can be painted" aria-label="Description">${esc(x.looks)}</textarea>
        ${x.prompt ? `<label class="help story-entity-prompt">Image prompt${x.prompt_exact ? '' : ' (rebuilt from the current settings; the exact one is kept from the next repaint)'}
          <textarea rows="4" readonly aria-label="Image prompt">${esc(x.prompt)}</textarea></label>` : ''}
        <div class="row"><label class="help">Images <input data-e="images" value="${esc(ranges((x.segments || []).map(i => i + 1)))}" placeholder="e.g. 1-3, 16" aria-label="Images it appears in"></label>
          <label class="check-toggle help" title="A character from your reference photos: its sheet is painted from your photo, and the scenes get the photo"><input type="checkbox" data-e="cast"${x.cast ? ' checked' : ''}> Uses my photo</label></div>
        <div class="row"><label class="help" title="A changed form (injured, mutated, broken, burned...) is painted from the sheet of the one it comes from, so it stays the same character, object or place">Form of
          <select data-e="base" aria-label="The reference this is a changed form of"><option value="">— not a changed form —</option>${(data.entities || []).filter(o => o.id && o.id !== x.id)
            .map(o => `<option value="${esc(o.id)}"${o.id === x.base ? ' selected' : ''}>${esc(o.name)}</option>`).join('')}</select></label></div>
        <div class="row story-entity-actions">${isNew ? '<button type="button" data-act="entity-add" class="primary">Add reference</button>' : `
          <button type="button" data-act="entity-save">Save</button>
          <button type="button" data-act="entity-repaint" title="Paint a new picture the next time an image that shows it is painted">Repaint</button>
          <button type="button" data-act="entity-upload">Upload my own picture</button>${x.image ? '<button type="button" data-act="entity-edit">Edit in Image Maker</button>' : ''}<input type="file" class="story-entity-file" accept="image/png,image/jpeg,image/webp" hidden>
          ${x.uploaded ? '<button type="button" data-act="entity-painted">Use a painted one</button>' : ''}
          <button type="button" data-act="entity-remove" class="danger">Remove</button>`}</div></div></div>`;
  }
  function entitiesHtml() {
    const list = data.entities || [];
    return `<details class="story-entities-editor" open><summary><b>References</b> <span class="help">${list.length} recurring
      character${list.length === 1 ? '' : 's'}, object${list.length === 1 ? '' : 's'} and place${list.length === 1 ? '' : 's'}. Each image is
      given the pictures of the ones it shows (a place as a location sheet, when a reference slot is free). Changes apply from the next image painted (Replace or Resume).</span></summary>
      <div class="story-entity-list">${list.map(entityCard).join('')}${entityCard(null)}</div></details>`;
  }
  async function entityChange(card, op, file) {
    const entry = { id: card.dataset.id || null };
    try {
      if (op === 'save' || op === 'add') {
        const value = name => card.querySelector(`[data-e="${name}"]`);
        Object.assign(entry, { name: value('name').value, kind: value('kind').value, looks: value('looks').value,
                               cast: value('cast').checked, base: value('base')?.value || '', images: parseImages(value('images').value),
                               photo: value('cast').checked ? (data.entities || []).find(x => x.id === entry.id)?.photo || '' : '' });
      }
      let r;
      if (file) { const form = new FormData(); form.append('id', entry.id); form.append('picture', file);
                  r = await api(`/api/jobs/${jobId}/story-entities`, form); }
      else r = await api(`/api/jobs/${jobId}/story-entities`, { op, entry });
      if (r.error) throw Error(r.error);
      const keep = edited; await load(); edited = keep; status(r.message);
    } catch (error) { status('Reference not changed: ' + (error.message || error)); }
  }

  function segmentHtml(seg) {
    const s = seg.story || { characters: '', environment: '', camera: '', beats: [], seconds: null };
    const summary = s.scene_direction === 'summary';
    const over = data.budget && seg.words > data.budget;
    return `<section class="story-segment" data-index="${seg.index}">
      <div class="story-seg-head">${seg.image ? `<img src="${esc(seg.image)}" alt="">` : '<div class="story-noimg">no image yet</div>'}
        <div><h3>Segment ${seg.index + 1}</h3>
        <div class="help">${seg.section ? `Song ${clock(seg.section[0])}–${clock(seg.section[1])}` : ''}${s.seconds ? ` · song section ${s.seconds} s` : ''}</div>
        <div class="story-lyrics">${esc(seg.lyrics)}</div></div></div>
      ${(seg.entities || []).length ? `<div class="story-seg-refs story-entities"><span class="help">References in this image:</span>
        ${seg.entities.map(entityHtml).join('')}</div>` : ''}
      <div class="story-seg-refs"><span class="help">References for this segment (image and video):</span>
        ${(seg.references || []).map(r => `<span class="story-ref"><img src="${esc(r.url)}" alt=""><button type="button" data-act="drop-ref" data-path="${esc(r.path)}" title="Remove">×</button>${tagLabel(referenceTag(r.path))}</span>`).join('')}
        ${(seg.references || []).length < 3 ? '<button type="button" data-act="add-ref">+ Add image</button><input type="file" class="story-ref-file" accept="image/png,image/jpeg,image/webp" hidden>' : ''}</div>
      <label>Image prompt <span class="help story-words ${over ? 'warn' : ''}">${seg.words} words${data.budget ? ` of about ${data.budget} the image model reads${over ? ' (condensed when regenerated)' : ''}` : ''}</span>
        <textarea data-field="prompt" rows="4">${esc(seg.prompt)}</textarea></label>
      ${data.video ? `<label>Art Style <span class="help">From Reference image prompt and the reference photo; editable for this scene.</span><textarea data-field="art_style" rows="3">${esc(s.art_style || '')}</textarea></label><div class="story-fields">
        <label>Characters <textarea data-field="characters" rows="2" placeholder="Who is in it, their appearance, and what each person is looking at. Face the camera only when the scene asks for it.">${esc(s.characters)}</textarea></label>
        <label>Environment <textarea data-field="environment" rows="2" placeholder="Place, time of day, weather and light">${esc(s.environment)}</textarea></label>
        <label>Camera <textarea data-field="camera" rows="2" placeholder="Framing and angle, then the one slow move: hold, push in, pull back, pan left, pan right, tilt up or tilt down (made in the edit; the AI camera holds still)">${esc(s.camera)}</textarea></label></div>
      ${summary ? `<label>Scene <span class="help">AI-written scene summary, without timed mini-scenes.</span><textarea data-field="scene" rows="5">${esc(s.scene || '')}</textarea></label>` : `<div class="story-beats"><div class="story-beat story-beat-head"><span title="Seconds from the start of this segment's clip (T = 0 when its painting appears)">From T+ (s)</span><span title="Seconds from the start of this segment's clip">To T+ (s)</span><span title="A note for you: the clip is shot from a still camera and its one move is made in the edit">Camera note</span><span>Scene and action</span><span></span></div>
        ${(s.beats || []).map(beatHtml).join('')}</div>
      <div class="row"><button type="button" data-act="add-beat">Add timed action</button>
        <span class="help">${s.seconds ? `Beats cover 0–${s.seconds} s; each runs until the next begins.` : ''}</span></div>`}` : ''}
    </section>`;
  }

  const beatHtml = b => `<div class="story-beat">
    <input type="number" step="0.1" min="0" data-beat="start" value="${esc(b.start ?? 0)}" aria-label="Beat start (seconds)">
    <input type="number" step="0.1" min="0" data-beat="end" value="${esc(b.end ?? '')}" aria-label="Beat end (seconds)">
    <textarea rows="2" data-beat="camera" aria-label="Camera">${esc(b.camera)}</textarea>
    <textarea rows="2" data-beat="action" aria-label="Scene and action">${esc(b.action)}</textarea>
    <button type="button" data-act="drop-beat" title="Remove this beat">×</button></div>`;

  function collect() {
    return [...dialog.querySelectorAll('.story-segment')].map(section => {
      const index = +section.dataset.index, field = name => section.querySelector(`[data-field="${name}"]`)?.value.trim() ?? '';
      const seg = { index, prompt: field('prompt') };
      if (data.video) {
        Object.assign(seg, { art_style: field('art_style'), scene_direction: data.segments[index].story?.scene_direction || 'timed', scene: field('scene'), moment: data.segments[index].story?.moment || '', characters: field('characters'), environment: field('environment'), camera: field('camera'),
          seconds: data.segments[index].story?.seconds,
          beats: [...section.querySelectorAll('.story-beat:not(.story-beat-head)')].map(row => ({
            start: +row.querySelector('[data-beat="start"]').value, end: +row.querySelector('[data-beat="end"]').value,
            camera: row.querySelector('[data-beat="camera"]').value.trim(), action: row.querySelector('[data-beat="action"]').value.trim()
          })).filter(b => b.action).sort((a, b) => a.start - b.start) });
      }
      return seg;
    });
  }

  function status(text) { const el = dialog.querySelector('.story-status'); if (el) el.textContent = text; }

  function wire() {
    const q = sel => dialog.querySelector(sel);
    dialog.oninput = event => { if (event.target.closest('.story-entity-card')) return; edited = true; status('Unsaved changes'); };
    dialog.onclick = async event => {
      const act = event.target.closest('[data-act]')?.dataset.act;
      if (!act) return;
      const section = event.target.closest('.story-segment');
      if (act === 'close') {
        if (edited && !q('.story-close-warn')) {
          status('You have unsaved changes. Save them, or press Close again to discard them.');
          q('.story-footer').append(Object.assign(document.createElement('span'), { className: 'story-close-warn' }));
          return;
        }
        dialog.close();
      }
      if (act === 'add-beat') {
        const rows = section.querySelectorAll('.story-beat:not(.story-beat-head)');
        const last = rows[rows.length - 1], start = last ? +last.querySelector('[data-beat="end"]').value || 0 : 0;
        section.querySelector('.story-beats').insertAdjacentHTML('beforeend', beatHtml({ start, end: start + 5, camera: '', action: '' }));
        edited = true;
      }
      const card = event.target.closest('.story-entity-card');
      if (card && act.startsWith('entity-')) {
        if (act === 'entity-upload') { card.querySelector('.story-entity-file').click(); return; }
        if (act === 'entity-edit') {
          const entity = (data.entities || []).find(e => e.id === card.dataset.id);
          if (entity) window.editInImageMaker?.({ id: entity.id, name: entity.name, url: entity.image });
          return;
        }
        if (act === 'entity-remove' && !card.dataset.confirm) { card.dataset.confirm = '1'; event.target.textContent = 'Remove? Click again'; return; }
        await entityChange(card, act.slice(7)); return;
      }
      if (act === 'project-refs') { dialog.close(); window.showProjectTab?.(); window.showProjectSubtab?.('references'); document.getElementById('references')?.scrollIntoView({ block: 'center' }); }
      if (act === 'add-ref') section.querySelector('.story-ref-file').click();
      if (act === 'drop-ref') {
        try { const r = await api(`/api/jobs/${jobId}/story-reference-remove`, { index: +section.dataset.index, path: event.target.dataset.path });
              if (r.error) throw Error(r.error); status(r.message); await load(); status(r.message); }
        catch (error) { status(error.message); }
      }
      if (act === 'drop-beat') { event.target.closest('.story-beat').remove(); edited = true; status('Unsaved changes'); }
      if (act === 'export') {
        const blob = new Blob([JSON.stringify({ kind: 'kinetic-lyrics-storyline', version: 1, exported: new Date().toISOString(),
          segments: collect().map((seg, k) => ({ ...seg, lyrics: data.segments[k].lyrics, section: data.segments[k].section })) }, null, 2)],
          { type: 'application/json' });
        const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `storyline-${jobId}.json` });
        link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        status('Storyline exported' + (edited ? ' (with your unsaved changes).' : '.'));
      }
      if (act === 'import') q('input[type=file]').click();
      if (act === 'write') {
        try { const r = await api(`/api/jobs/${jobId}/story-write`, {}); status(r.message || 'Queued.'); }
        catch (error) { status(error.message); }
      }
      if (act === 'save') save(false);
      if (act === 'regenerate' || act === 'confirm-regenerate') {   // a bad tag is dropped silently, across the whole song
        const problems = window.storyTagProblems?.(dialog) || [], note = q('.story-tag-warning');
        note.hidden = !problems.length;
        note.textContent = problems.length ? 'Fix before regenerating, no picture has these tags: '
          + problems.map(p => `Illustration ${p.number}: ${p.tags.join(', ')}`).join(' · ') : '';
        if (problems.length) { q('.story-warning').hidden = true; note.scrollIntoView({ block: 'nearest' }); return; }
      }
      if (act === 'regenerate') { q('.story-warning').hidden = false; q('.story-warning').scrollIntoView({ block: 'nearest' }); }
      if (act === 'cancel-regenerate') q('.story-warning').hidden = true;
      if (act === 'confirm-regenerate') { q('.story-warning').hidden = true; save(true); }
    };
    dialog.querySelectorAll('.story-entity-file').forEach(input => input.onchange = event => {
      const file = event.target.files[0]; if (file) entityChange(event.target.closest('.story-entity-card'), 'upload', file);
    });
    dialog.querySelectorAll('.story-ref-file').forEach(input => input.onchange = async event => {
      const file = event.target.files[0]; if (!file) return;
      if (typeof imageModelTakesReferences === 'function' && !imageModelTakesReferences(data?.image_model || $('imageModel')?.value))
        toast(`${(data?.image_model || 'This image model').split('/').pop()} does not read reference images: this segment's image ignores it (its clip prompt still describes it). Choose an image model that takes references to use it.`);
      const form = new FormData(); form.append('index', event.target.closest('.story-segment').dataset.index); form.append('reference', file);
      try { const r = await api(`/api/jobs/${jobId}/story-reference`, form); if (r.error) throw Error(r.error);
            await load(); status(r.message); }
      catch (error) { status(error.message); }
    });
    q('input[type=file]').onchange = async event => {
      const file = event.target.files[0]; event.target.value = '';
      if (!file) return;
      try {
        const imported = JSON.parse(await file.text());
        if (!Array.isArray(imported?.segments)) throw Error('This file is not a storyline export.');
        if (imported.segments.length !== data.segments.length)
          throw Error(`This storyline has ${imported.segments.length} segments; this song has ${data.segments.length}.`);
        imported.segments.forEach((seg, k) => {
          data.segments[k].prompt = seg.prompt || data.segments[k].prompt;
          data.segments[k].words = data.segments[k].prompt.split(/\s+/).filter(Boolean).length;
          if (data.video) data.segments[k].story = { ...(data.segments[k].story || {}), art_style: seg.art_style ?? data.segments[k].story?.art_style ?? '', scene_direction: seg.scene_direction || 'timed', scene: seg.scene || '', moment: seg.moment || '', characters: seg.characters || '',
            environment: seg.environment || '', camera: seg.camera || '', beats: Array.isArray(seg.beats) ? seg.beats : [] };
        });
        render(); edited = true; status(`Imported ${file.name}. Review it, then Save or Regenerate.`);
      } catch (error) { status('Not imported: ' + error.message); }
    };
  }

  async function save(regenerate) {
    status(regenerate ? 'Saving and restarting image generation…' : 'Saving…');
    try {
      const result = await api(`/api/jobs/${jobId}/story`, { segments: collect(), regenerate });
      if (result.error) throw Error(result.error);
      edited = false; status(result.message || 'Saved.');
      if (!regenerate) { const keep = result.message; await load(); status(keep); }
    } catch (error) { status('Not saved: ' + error.message); }
  }
}
document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', setupStoryline) : setupStoryline();
