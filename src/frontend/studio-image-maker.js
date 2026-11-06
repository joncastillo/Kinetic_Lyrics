// Image Maker: pictures that belong to no song. A template (or none) fills the prompt, which stays editable; prompts and
// reference pictures are kept for later. Tags in the prompt work as in Replace or verify (see studio-tag-picker.js).
(() => {
  const dialog = $('imageMaker'), opener = $('openImageMaker');
  if (!dialog || !opener) return;
  const field = id => $('maker' + id);
  const running = status => ['starting', 'planning', 'waiting', 'loading', 'painting', 'animating'].includes(status?.state);
  const SETTINGS = ['Model', 'Width', 'Height', 'Format', 'Quality', 'Steps', 'Seed', 'Count', 'Folder', 'Name', 'Output', 'Motion', 'Duration'];
  let info = null, attached = [], timer = 0, replacing = null, viewingRequest = null;
  const referenceUsage=new Map();
  const labelText = name => String(name||'').replace(/\.(png|jpe?g|webp)$/i,'');
  const imageTag = name => referenceTag(labelText(name));
  const referenceUrl = name => viewingRequest?.references?.includes(name) ? '/api/image-maker/request-reference?' + new URLSearchParams({request_id:viewingRequest.request_id||'',name}) : '/api/image-maker/reference?name=' + encodeURIComponent(name);
  const regionGuide=window.createEditRegionGuide({overlay:field('RegionOverlay'),list:field('RegionList'),drawButton:field('RegionDraw'),moveButton:field('RegionMove'),clearButton:field('RegionClear'),sourceButton:field('RegionSource'),status:field('RegionStatus'),onChange:()=>{if(info){renderReferences();check()}},onSource:(url,name)=>preview(url,name)});
  window.imageEditorTags = () => (info?.references||[]).map(imageTag);
  function attachTypedReferences() {
    if(!info)return;
    const normalize=value=>String(value).toLowerCase().replace(/\.(png|jpe?g|webp)$/i,'').replace(/[^a-z0-9]/g,'');
    const tags=[...field('Prompt').value.matchAll(/@(?:"([^"]+)"|([\w.-]+))/g)].map(match=>normalize(match[1]||match[2]));
    const added=info.references.filter(name=>tags.includes(normalize(name))&&!attached.includes(name));
    if(added.length){attached.push(...added);renderReferences()}
  }
  function preview(url, label, prompt = '') {
    field('PreviewImage').src=url;field('PreviewImage').alt=labelText(label);field('PreviewImage').hidden=false;
    field('PreviewLabel').textContent=labelText(label);field('PreviewLink').href=url;field('PreviewLink').hidden=false;
    field('PromptUsed').value=prompt||'';field('CopyPromptUsed').disabled=!prompt;
    regionGuide.showFor(url);
  }
  function requestSize(width, height) {
    let w=Number(width),h=Number(height);
    if(!Number.isFinite(w)||w<=0)w=1024;if(!Number.isFinite(h)||h<=0)h=1024;
    const scale=Math.min(1,2048/w,2048/h);
    return {width:Math.min(2048,Math.max(256,Math.floor(w*scale/32)*32)),height:Math.min(2048,Math.max(256,Math.floor(h*scale/32)*32))};
  }
  function editorMode(on) {
    dialog.classList.toggle('editing-reference',on);
    field('Heading').textContent=on?(replacing?.type==='illustration'?'Edit image':'Edit reference'):'Image Maker';dialog.setAttribute('aria-label',field('Heading').textContent);
    field('NameLabel').textContent=on?'Label name':'File name';
    for(const id of ['Saved','Output','Template','Size','Width','Height','Format','Quality','Steps','Seed','Count','Folder']) {
      const element=field(id);const wrapper=['Saved','Size','Format','Folder'].includes(id)?element.closest('.maker-row'):element.closest('label');
      if(wrapper)wrapper.hidden=on;
    }
    if(on){field('SubjectRow').hidden=true;field('MotionRow').hidden=true;field('Count').value=1;field('Output').value='image';field('Seed').value='';field('Name').value=labelText(field('Name').value);
      const size=requestSize(field('Width').value,field('Height').value);field('Width').value=size.width;field('Height').value=size.height;
    }
  }

  // The worker already queues on the shared GPU lock. Show that same request outside the dialog;
  // opening or closing Image Maker must never submit it again.
  function renderHeaderQueue(answer) {
    let host = $('imageEditQueue');
    if (!host) {
      host = document.createElement('div'); host.id = 'imageEditQueue'; host.className = 'replacement-queue';
      host.setAttribute('aria-label', 'In-Image Edit Queue'); host.setAttribute('role', 'status');
      ($('queueSlot') || $('actionProgress')).append(host);
    }
    const status = answer.status || {};
    const keys=new Set(), names=new Set();
    const nameKey=q=>String(q?.label||q?.edit_target?.label||q?.name||q?.request_name||'').replace(/_edit$/i,'').replace(/[^a-z0-9]/gi,'').toLowerCase();
    if(running(status)&&answer.edit_target)keys.add(answer.edit_target.job+':'+answer.edit_target.id);
    if(running(status))names.add(nameKey(answer.request||answer));
    const pending = (answer.queued || []).filter(q=>{const key=q.edit_target?q.edit_target.job+':'+q.edit_target.id:q.request_id||q.name;if(keys.has(key)||!q.edit_target&&names.has(nameKey(q))||status.state==='done'&&q.request_id&&q.request_id===answer.request?.request_id)return false;keys.add(key);names.add(nameKey(q));return true});
    host.hidden = !running(status) && !pending.length;
    if (host.hidden) { host.replaceChildren(); return; }
    const group = document.createElement('div'); group.className = 'replacement-queue-group';
    const title = document.createElement('strong'); title.className = 'replacement-queue-title';
    title.textContent = 'In-Image Edit Queue';
    const item = document.createElement('button'); item.type = 'button';
    item.className = 'replacement-queue-pill ' + (['starting', 'waiting'].includes(status.state) ? 'queued' : 'active');
    const label = request => referenceTag(request.label || request.edit_target?.label || request.edit_target?.id || request.references?.[0]?.replace(/\.[^.]+$/,'') || request.request_name || request.name || 'Edit');
    item.textContent = label(answer.request || answer);
    item.title = (status.message || status.state) + ' · Edit this request'; item.onclick = () => openRequest(answer.request || {name:answer.request_name,edit_target:answer.edit_target});
    group.append(title);
    if (running(status)) group.append(item);
    for (const request of pending) {
      const pill = document.createElement('button'); pill.type = 'button'; pill.className = 'replacement-queue-pill queued';
      pill.textContent = label(request); pill.title = 'Queued · View this edit'; pill.onclick = () => openRequest(request); group.append(pill);
    }
    host.replaceChildren(group);
  }
  let headerPolling = false;
  async function pollHeaderQueue() {
    if (headerPolling) return;
    headerPolling = true;
    try {
      const response = await fetch('/api/image-maker/status');
      if (response.ok) renderHeaderQueue(await response.json());
    } catch {} finally { headerPolling = false; }
  }
  setInterval(pollHeaderQueue, 3000);
  pollHeaderQueue();

  const template = () => info.templates.find(t => t.id === field('Template').value) || info.templates[0];
  const model = () => info.models.find(m => m.id === field('Model').value);

  function choices(select, items, value) {
    select.replaceChildren(...items.map(([id, label]) => new Option(label, id)));
    if (value !== undefined && items.some(([id]) => id === value)) select.value = value;
  }

  function chooseTemplate(keepText) {
    const t = template();
    field('SubjectRow').hidden = t.id === 'none';
    field('SubjectLabel').textContent = t.subject || 'Subject';
    if (keepText) return;
    field('Prompt').value = t.text;
    field('Width').value = t.width; field('Height').value = t.height;
    field('Prompt').dispatchEvent(new Event('input', { bubbles: true }));
  }

  function chooseModel() {
    const m = model();
    if (!m) return;
    field('Steps').placeholder = m.steps;
    field('ModelNote').textContent = (m.on_disk ? '' : `Not downloaded yet: the first run downloads about ${m.disk_gb || '?'} GB. `)
      + (m.references ? `Reads up to ${m.max_references} reference pictures. ` : 'Does not read reference pictures. ') + (m.license || '');
    check();
  }

  function renderReferences() {
    const names = info.references || [];
    attached = attached.filter(name => names.includes(name));
    if(!attached.includes(regionGuide.source)&&(regionGuide.source||attached.length)){
      const source=attached[0]||'';regionGuide.load([],source,source?referenceUrl(source):'');
    }
    field('Refs').replaceChildren(...names.map(name => {
      const on = attached.includes(name), item = document.createElement('div');
      item.className = 'reuse-ref' + (on ? ' attached' : '');
      const pick = document.createElement('button');
      pick.type = 'button'; pick.className = 'reuse-pick'; pick.setAttribute('aria-pressed', String(on));
      pick.title = (on ? 'Stop using ' : 'Use ') + name;
      const img = document.createElement('img');
      img.src = viewingRequest?.references?.includes(name) ? '/api/image-maker/request-reference?' + new URLSearchParams({request_id:viewingRequest.request_id||'',name}) : '/api/image-maker/reference?name=' + encodeURIComponent(name); img.alt = name;
      const label = document.createElement('small'); label.textContent = labelText(name);
      pick.append(img, label);
      pick.onclick = () => { attached = on ? attached.filter(n => n !== name) : [...attached, name];if(!on&&!regionGuide.regions.length)regionGuide.load([],name,referenceUrl(name));preview(img.src,name);renderReferences(); check(); };
      const drop = document.createElement('button');
      drop.type = 'button'; drop.className = 'reuse-drop'; drop.textContent = '×'; drop.title = 'Delete ' + name; drop.setAttribute('aria-label', drop.title);
      const uses=[...(on?['Selected for this edit']:[]),...(info.history||[]).filter(i=>(i.references||[]).includes(name)).map(i=>'Edit history: '+labelText(i.name)),...(info.queued||[]).filter(i=>(i.references||[]).includes(name)).map(i=>'Queued edit: '+labelText(i.name))];
      if(running(info.status)&&(info.request?.references||[]).includes(name))uses.push('Current edit: '+labelText(info.request.label||info.request.name));
      drop.disabled=!!uses.length;drop.title=uses.length?'Cannot delete: '+uses.join('; '):'Delete '+labelText(name);
      if(!uses.length){
        const cached=referenceUsage.get(name);
        drop.disabled=true;drop.title='Checking where this reference is used…';
        const applyUsage=used=>{drop.disabled=!!used.length;drop.title=used.length?'Cannot delete: '+used.join('; '):'Delete unused reference '+labelText(name)};
        if(cached&&Date.now()-cached.at<10000)applyUsage(cached.uses);
        else api('/api/image-maker/reference-usage',{name,selected_references:attached}).then(result=>{const used=result.uses||[];referenceUsage.set(name,{uses:used,at:Date.now()});applyUsage(used)}).catch(()=>{drop.disabled=true;drop.title='Deletion disabled: the server could not verify reference usage. Restart Studio to load the usage guard.'});
      }
      drop.onclick = async () => {
        try{const check=await api('/api/image-maker/reference-usage',{name,selected_references:attached});if(check.uses?.length){drop.disabled=true;drop.title='Cannot delete: '+check.uses.join('; ');field('Status').textContent=drop.title;return}}
        catch(error){field('Status').textContent='Could not check reference usage: '+error.message;return}
        send('reference-delete', { name, selected_references:attached });
      };
      item.append(pick, drop);
      if (on) item.append(tagCaption(imageTag(name)));
      return item;
    }));
    field('RefsEmpty').hidden = !!names.length;
    field('Inputs').replaceChildren(...attached.map(name=>{
      const card=document.createElement('figure'),pick=document.createElement('button'),img=document.createElement('img');
      pick.type='button';img.src=referenceUrl(name);img.alt=labelText(name);pick.append(img);pick.onclick=()=>{if(!regionGuide.regions.length)regionGuide.load([],name,referenceUrl(name));preview(img.src,name)};
      const remove=document.createElement('button');remove.type='button';remove.textContent='Remove';remove.onclick=()=>{attached=attached.filter(n=>n!==name);renderReferences();check()};
      card.append(pick,tagCaption(imageTag(name)),remove);return card;
    }));
    field('InputsEmpty').hidden=!!attached.length;
    const guide=regionGuide.thumbnail();
    if(guide){const card=document.createElement('figure'),img=document.createElement('img'),caption=document.createElement('figcaption');img.src=guide;img.alt='Numbered edit-region guide';caption.textContent='Region guide · '+regionGuide.regions.length+' regions';card.append(img,caption);field('Inputs').append(card)}
  }

  function renderPrompts() {
    const current = field('Saved').value;
    choices(field('Saved'), [['', 'Saved prompts…'], ...(info.prompts || []).map(p => [p.name, p.name])], current);
  }

  function useRecipe(recipe) {
    recipe = 'file_name' in recipe ? { ...recipe, name: recipe.file_name } : recipe;   // a saved prompt's name is its own
    field('Template').value = recipe.template || 'none';
    chooseTemplate(true);
    field('Subject').value = recipe.subject || '';
    field('Prompt').value = recipe.prompt || '';
    attached = (recipe.references || []).filter(name => info.references.includes(name));
    const source=recipe.region_source||attached[0]||'';regionGuide.load(recipe.regions||[],source,source?referenceUrl(source):'');
    for (const name of SETTINGS) { const key = name.toLowerCase(); if (recipe[key] !== undefined && recipe[key] !== null) field(name).value = recipe[key]; }
    field('PreserveOutside').checked = recipe.preserve_outside_regions ?? true;
    field('Output').value = recipe.output || 'image'; field('Duration').value = recipe.duration || 5;
    syncOutput();
    chooseModel(); renderReferences();
    for (const id of ['Subject', 'Prompt']) field(id).dispatchEvent(new Event('input', { bubbles: true }));
  }

  // The picture's own references come back with it, into the library if they have left it since.
  async function useAgain(item) {
    viewingRequest = null;
    let used = item.references || [], renamed = {}, missing = [];
    try {
      const answer = await api('/api/image-maker/picture-references', { id: item.id });
      if (answer.error) throw Error(answer.error);
      ({ used, renamed, missing } = answer);
      Object.assign(info, answer);
    } catch { missing = used.filter(name => !info.references.includes(name)); }
    const retag = text => Object.entries(renamed).reduce((value, [old, name]) => value.split('@' + old).join('@' + name), text || '');
    useRecipe({ ...item, seed: '', references: used, region_source:renamed[item.region_source]||item.region_source, prompt: retag(item.prompt), subject: retag(item.subject) });
    take({});
    field('Status').classList.remove('maker-failed');
    field('Status').textContent = missing.length ? `Loaded, but these references are gone: ${missing.join(', ')}` : 'Loaded with its references. Change anything, then Generate.';
  }

  // A picture made here becomes the song's reference, through the same route as uploading one.
  async function useForReference(item, url, target = replacing) {
    try {
      if (!target) throw Error('Choose the reference to replace');
      const blob = await (await fetch(url)).blob();
      const form = new FormData();
      if(target.type==='illustration'){form.append('index',target.index);form.append('replacement',blob,item.path.split(/[\\/]/).pop())}
      else{form.append('id', target.id); form.append('picture', blob, item.path.split(/[\\/]/).pop());form.append('regenerate_dependents','true')}
      const answer = await api(`/api/jobs/${target.job}/${target.type==='illustration'?'replace':'story-entities'}`, form);
      if (answer.error) throw Error(answer.error);
      const library = new FormData();
      library.append('reference', blob, referenceTag(target.name||target.label||item.name||item.path.split(/[\\/]/).pop()).slice(1)+'.png');
      const added = await api('/api/image-maker/reference', library);
      if (added.error) throw Error('Reference replaced, but the reusable picture could not be saved: '+added.error);
      viewingRequest = null;
      take(added);
      field('Status').classList.remove('maker-failed');
      field('Status').textContent = answer.message || 'Replaced.';
      if (typeof poll === 'function') { gallerySignature = ''; await window.poll?.(); }
      if(target.type!=='illustration'){
        const fresh=await api(`/api/jobs/${target.job}`),current=(fresh.entity_references||[]).find(e=>e.id===target.id);
        if(current?.url){await window.editInImageMaker({...target,...current});field('Status').textContent=answer.message||'Reference selected.';return;}
      }
      stopReplacing();
    } catch (error) { field('Status').textContent = 'Could not replace it: ' + (error.message || error); field('Status').classList.add('maker-failed'); }
  }
  function stopReplacing() {
    replacing = null;
    viewingRequest = null;
    regionGuide.load([],'','');
    editorMode(false);
    field('Replacing').hidden = true;
    renderResults();
  }

  async function discardReferenceVersion(value, target) {
    try {
      const result=await api(`/api/jobs/${target.job}/reference-version`,{id:target.id,...value},120000);
      if(result.error)throw Error(result.error);
      gallerySignature='';await window.poll?.();
      const fresh=await api(`/api/jobs/${target.job}`),current=(fresh.entity_references||[]).find(e=>e.id===target.id);
      take(await api('/api/image-maker/status'));
      if(current?.url)await window.editInImageMaker({...target,...current});
      field('Status').textContent=result.message||'Version discarded.';toast(result.message||'Version discarded.');
    } catch(error){field('Status').textContent=error.message||String(error);field('Status').classList.add('maker-failed')}
  }

  function renderResults() {
    const context=replacing||viewingRequest?.edit_target;
    const name=context?.name||context?.label||viewingRequest?.label;
    const items = (info.history || []).filter(item => !context&&!viewingRequest ||
      (context&&item.edit_target ? item.edit_target.job===context.job&&item.edit_target.id===context.id :
      item.name===imageTag(name).slice(1)+'_edit'||item.name===imageTag(name).slice(1)||imageTag(item.references?.[0])===imageTag(name)));
    const entity=context&&typeof entityReferences==='function'?entityReferences(state).find(e=>e.id===context.id):null;
    const sources=entity?.history?.length?entity.history:entity?[...(entity.url?[{url:entity.url}]:[]),...(entity.earlier||[]).map(url=>({url}))]:replacing?.url?[{url:replacing.url}]:[];
    field('ResultsEmpty').hidden = !!items.length;
    const signature = JSON.stringify([items.map(i=>[i.id,i.reference_applied]),context?.id,sources,jobId]);
    if (field('Results').dataset.signature === signature) return;
    field('Results').dataset.signature = signature;
    field('Results').replaceChildren(...items.map(item => {
      const card = document.createElement('figure');
      card.className = 'maker-result';
      const isVideo = item.video || /\.mp4$/i.test(item.path);
      const img = document.createElement(isVideo ? 'video' : 'img');
      img.src = '/api/image-maker/picture?id=' + item.id;
      if (isVideo) { img.controls = true; img.muted = true; img.loop = true; img.playsInline = true; img.preload = 'metadata'; img.setAttribute('aria-label', item.name); }
      else { img.alt = item.name; img.loading = 'lazy'; img.onclick = () => preview(img.src, item.name, item.sent_prompt||item.prompt); }
      const caption = document.createElement('figcaption');
      caption.textContent = labelText(item.path.split(/[\\/]/).pop())+(item.reference_applied?' · Previously applied':'');
      const again = document.createElement('button');
      again.type = 'button'; again.textContent = 'Use this prompt';
      again.title = 'Load the prompt and settings this picture was made with, to refine them';
      again.onclick = () => useAgain(item);
      const drop = document.createElement('button');
      drop.type = 'button'; drop.className = 'reuse-drop'; drop.textContent = '×';
      drop.title = (context?'Discard ':'Delete ') + item.path.split(/[\\/]/).pop(); drop.setAttribute('aria-label', drop.title);
      if(context&&!isVideo){drop.textContent='Discard';drop.onclick=()=>discardReferenceVersion({maker_id:item.id},context)}
      else drop.onclick = () => send('picture-delete', { id: item.id });
      card.append(img, caption, again, drop);

      const matchesReference = replacing && (item.edit_target ? item.edit_target.job===replacing.job && item.edit_target.id===replacing.id :
        (item.references||[]).some(name=>referenceTag(name.replace(/\.[^.]+$/,''))===referenceTag(replacing.name)) || item.name===referenceTag(replacing.name).slice(1)+'_edit');
      if (!isVideo && matchesReference) {
        const use = document.createElement('button');
        use.type = 'button'; use.className = 'primary'; use.textContent = 'Use for ' + replacing.name;
        use.onclick = () => useForReference(item, img.src);
        card.append(use);
      } else if (!isVideo && jobId && typeof entityReferences==='function') {
        const entities=entityReferences(state).filter(e=>e.id);
        if (entities.length) {
          const target=document.createElement('select'); target.setAttribute('aria-label','Reference to replace');
          target.replaceChildren(...entities.map(e=>new Option(referenceTag(e.name),e.id)));
          const use=document.createElement('button');use.type='button';use.textContent='Use as reference';
          use.onclick=()=>useForReference(item,img.src,{id:target.value,job:jobId});
          card.append(target,use);
        }
      }
      return card;
    }));
    for(const [index,source] of sources.entries()) {
      const card=document.createElement('figure');card.className='maker-result';const img=document.createElement('img');img.src=source.url;img.alt=labelText(name);img.loading='lazy';img.onclick=()=>preview(source.url,name,source.prompt);
      const caption=document.createElement('figcaption');caption.textContent=source.url===entity?.url?'Current reference':index===sources.length-1?'Original reference':'Previous reference';
      card.append(img,caption);
      if(context){
        const use=document.createElement('button');use.type='button';use.className='primary';
        use.textContent=source.url===entity?.url?'Selected reference':'Use as reference';use.disabled=source.url===entity?.url;
        use.onclick=()=>useForReference({path:source.path||labelText(name)+'.png'},source.url,context);
        card.append(use);
        const discard=document.createElement('button');discard.type='button';discard.textContent='Discard';
        discard.title=source.url===entity?.url?'Discard this version and restore the previous reference':'Discard this history version';
        discard.onclick=()=>discardReferenceVersion({url:source.url},context);card.append(discard);
      }
      if(source.review){const reason=document.createElement('p');reason.className='help';reason.textContent=(source.review.passed?'Passed checker: ':'Failed checker: ')+[source.review.summary,...(source.review.issues||[])].filter(Boolean).join('; ');card.append(reason)}
      field('Results').append(card);
    }
    field('ResultsEmpty').hidden=!!(items.length||sources.length);
  }

  function renderStatus() {
    const status = info.status || {}, busy = running(status);
    field('Generate').hidden = false; field('Generate').textContent = viewingRequest ? 'Save and requeue edit' : replacing||busy ? 'Queue edit' : 'Generate';
    field('Stop').hidden = dialog.classList.contains('editing-reference') || !busy; field('Stop').textContent = 'Stop current';
    field('Status').textContent = (status.message || '') + ((info.queued||[]).length ? ` · ${info.queued.length} queued` : '');
    field('Status').classList.toggle('maker-failed', status.state === 'failed');
    clearTimeout(timer);
    if (busy && dialog.open) timer = setTimeout(poll, 1500);
  }

  function take(answer) {
    Object.assign(info, answer);
    renderHeaderQueue(info);
    renderReferences(); renderPrompts(); renderResults(); renderStatus(); check();
  }
  async function poll() {
    if (!dialog.open) return;
    try { take(await (await fetch('/api/image-maker/status')).json()); } catch { timer = setTimeout(poll, 3000); }
  }
  async function send(action, body) {
    try { const answer = await api('/api/image-maker/' + action, body); if (answer.error) throw Error(answer.error); take(answer); return true; }
    catch (error) { field('Status').textContent = error.message || String(error); field('Status').classList.add('maker-failed'); return false; }
  }

  // Generate waits until every tag names a picture in use, and the model can read those pictures.
  function problems() {
    const out = [], m = model();
    const bad = window.invalidTagsIn?.([field('Prompt'), field('Subject')]) || [];
    if (bad.length) out.push(`No picture in use has ${bad.length > 1 ? 'these tags' : 'this tag'}: ${bad.join(', ')}`);
    if (m && attached.length > m.max_references) out.push(m.references ? `${m.name} reads at most ${m.max_references} reference pictures` : `${m.name} does not read reference pictures`);
    if(regionGuide.regions.length){if(m?.id!=='Qwen/Qwen-Image-2.1')out.push('Region guides require Qwen Image 2.1');if(!attached.includes(regionGuide.source))out.push('Keep the guide source selected, or clear the regions');if(m&&attached.length+1>m.max_references)out.push('The region guide uses one reference slot; remove another reference picture')}
    if (field('Prompt').value.includes('{subject}') && !field('Subject').value.trim()) out.push(`Fill in "${template().subject}"`);
    if (!field('Prompt').value.trim()) out.push('Write a prompt');
    if (!field('Folder').value.trim()) out.push('Choose an output folder');
    return out;
  }
  function check() {
    const regions=!!regionGuide.regions.length;
    field('PreserveOutside').disabled=!regions;
    if(regions&&field('PreserveOutside').checked)field('Format').value='png';
    const list = info ? problems() : [];
    field('Warning').hidden = !list.length;
    field('Warning').textContent = list.join(' · ');
    field('Generate').classList.toggle('tag-blocked', !!list.length);
    return list;
  }

  const recipe = () => ({ template: field('Template').value, subject: field('Subject').value, prompt: field('Prompt').value, references: attached,
    regions:regionGuide.regions,region_source:regionGuide.source,preserve_outside_regions:!!regionGuide.regions.length&&field('PreserveOutside').checked,
    model: field('Model').value, ...requestSize(field('Width').value,field('Height').value), format: field('Format').value, quality: field('Quality').value,
    steps: field('Steps').value, seed: field('Seed').value, count: field('Count').value, folder: field('Folder').value, name: field('Name').value,
    output: field('Output').value, motion: field('Motion').value, duration: field('Duration').value, ai_model: $('aiModel')?.value || 'auto',
    edit_target: replacing ? {job:replacing.job,id:replacing.id,type:replacing.type,index:replacing.index,label:labelText(field('Name').value)||replacing.name,reference_generation:replacing.reference_generation||'',reference_edit_revision:replacing.reference_edit_revision||''} : undefined });
  function syncOutput(){field('Output').value='image';field('MotionRow').hidden=true;}

  async function open() {
    if (!dialog.open) dialog.showModal();
    if (info) return poll();
    field('Status').textContent = 'Loading…';
    try {
      const answer = await (await fetch('/api/image-maker')).json();
      if (answer.error) throw Error(answer.error);
      info = answer;
    } catch (error) { field('Status').textContent = 'Restart Studio to use Image Maker. ' + (error.message || ''); return; }
    choices(field('Template'), info.templates.map(t => [t.id, t.name]), 'scene');
    choices(field('Model'), info.models.map(m => [m.id, m.name + (m.on_disk ? '' : ' (not downloaded)')]), $('imageModel')?.value);
    choices(field('Format'), info.formats.map(f => [f, f === 'jpeg' ? 'JPEG' : f === 'webp' ? 'WebP' : 'PNG']), 'png');
    field('Count').max = info.max_count; field('Folder').value = info.default_folder;
    chooseTemplate(false); chooseModel(); take({});
  }
  opener.onclick = open;

  async function openRequest(request) {
    await open();
    if (!info) return;
    try {
      const query=new URLSearchParams();
      if(request?.request_id)query.set('request_id',request.request_id);
      else if(request?.edit_target?.id){query.set('entity',request.edit_target.id);query.set('job',request.edit_target.job)}
      else if(request?.name)query.set('name',request.name);
      const fresh=await api('/api/image-maker/request?'+query);
      if(fresh.request)request=fresh.request;
    } catch(error) {
      if(!request?.prompt){field('Status').textContent='Could not load this queued edit: '+error.message;return;}
    }
    if (!request?.prompt) {
      field('Status').textContent = 'This server predates saved edit details. Restart Studio to recover the queued request and its source image.';
      return;
    }
    viewingRequest = request;
    info.references = [...new Set([...(info.references||[]), ...(request.references||[])])];
    const target = request.edit_target;
    const entity = !target && typeof entityReferences==='function' ? entityReferences(state).find(e=>referenceTag(e.name)===referenceTag(request.label)) : null;
    replacing = target ? {...target,name:target.label||request.label,before:[]} : entity ? {id:entity.id,job:jobId,name:entity.name,before:[]} : null;
    useRecipe(request);
    editorMode(true);
    if(attached[0])preview(referenceUrl(attached[0]),request.label);
    field('Replacing').hidden = false;
    field('ReplacingText').textContent = 'Edit for '+referenceTag(request.label)+'. Save and requeue updates this request. If it is running, that edit is stopped and restarted with your changes.';
    renderResults();
    renderStatus();
  }

  // From a reference in the song: its picture goes in as a reference, and the prompt starts from it.
  window.editInImageMaker = async entity => {
    if(!entity.url){toast('This reference is waiting to be painted. Use the regenerate arrow to edit its prompt.');return;}
    await open();
    viewingRequest = null;
    if (!info?.models) return;
    replacing={id:entity.id,name:entity.name,type:entity.type,index:entity.index,url:entity.url,job:jobId,before:[]};
    editorMode(true);preview(entity.url,entity.name);
    field('Prompt').value=`Do not change anything else in ${imageTag(entity.name)} other than: `;
    try {
      const answer = await api('/api/image-maker/project-references', {job:jobId,id:entity.id,type:entity.type,index:entity.index});
      if (answer.error) throw Error(answer.error);
      take(answer);
      const name = (answer.added || [])[0];
      field('PreserveOutside').checked=true;
      const blob = await (await fetch(referenceUrl(name))).blob();
      replacing = { id: entity.id, name: entity.name, type:entity.type,index:entity.index,url:entity.url, job: jobId, reference_generation:answer.reference_generation, reference_edit_revision:answer.reference_edit_revision, before: (info.history || []).map(i => i.id) };
      field('Output').value = 'image'; syncOutput();
      field('Template').value = 'none'; chooseTemplate(true);
      field('Prompt').value = `Do not change anything else in ${imageTag(name)} other than: `;
      field('Name').value = imageTag(entity.name).slice(1);
      const dimensions=await createImageBitmap(blob);field('Width').value=dimensions.width;field('Height').value=dimensions.height;dimensions.close();
      editorMode(true);preview(entity.url,entity.name);
      attached = [name];regionGuide.load([],name,referenceUrl(name));preview(referenceUrl(name),entity.name);
      field('ReplacingText').textContent = `Editing ${entity.name}. Queue the change; the completed image automatically replaces this ${entity.type==='illustration'?'illustration':'recurring reference'}.`;
      field('Replacing').hidden = false;
      renderReferences(); renderResults(); chooseModel();
      renderStatus();
      field('Prompt').dispatchEvent(new Event('input', { bubbles: true }));
      field('Prompt').focus(); field('Prompt').setSelectionRange(9999, 9999);
    } catch (error) { field('Status').textContent = 'Could not load the picture: ' + (error.message || error); }
  };
  field('ReplacingStop').onclick = stopReplacing;
  field('CopyPromptUsed').onclick=()=>{field('Prompt').value=field('PromptUsed').value;field('Prompt').dispatchEvent(new Event('input',{bubbles:true}));field('Prompt').focus();};
  $('closeImageMaker').onclick = () => dialog.close();
  field('Template').onchange = () => chooseTemplate(false);
  field('Output').onchange = syncOutput;
  field('Model').onchange = chooseModel;
  field('Size').onchange = () => { const [w, h] = field('Size').value.split('x'); if (w) { field('Width').value = w; field('Height').value = h; } field('Size').value = ''; };
  dialog.addEventListener('input', event=>{if(event.target===field('Prompt'))attachTypedReferences();check()});
  field('Files').onchange = async event => {
    const files = [...event.target.files]; event.target.value = '';
    if (!files.length) return;
    const form = new FormData(); files.forEach(file => form.append('reference', file));
    try { const answer = await api('/api/image-maker/reference', form); if (answer.error) throw Error(answer.error);
      attached = [...attached, ...(answer.added || []).filter(name => !attached.includes(name))]; take(answer); }
    catch (error) { field('Status').textContent = error.message || String(error); }
  };
  field('Choose').onclick = async () => {
    field('Status').textContent = 'Choose a folder in the window that opened…';
    try { const answer = await api('/api/image-maker/choose-folder', {}); if (answer.folder) field('Folder').value = answer.folder; field('Status').textContent = ''; check(); }
    catch (error) { field('Status').textContent = error.message || String(error); }
  };
  field('Save').onclick = () => {
    const name = field('SaveName').value.trim() || field('Saved').value;
    if (!name) { field('Status').textContent = 'Name the prompt to save it.'; return; }
    send('prompt', { ...recipe(), file_name: field('Name').value, name }).then(done => { if (done) { field('Saved').value = name; field('SaveName').value = ''; field('Status').textContent = `Saved "${name}".`; } });
  };
  field('Saved').onchange = () => { const saved = info.prompts.find(p => p.name === field('Saved').value); if (saved) { useRecipe(saved); field('SaveName').value = saved.name; } };
  field('Forget').onclick = () => { const name = field('Saved').value; if (name) send('prompt-delete', { name }); };
  field('Generate').onclick = async () => { if (!check().length && !field('Generate').disabled) {
    field('Generate').disabled = true;
    if(replacing||viewingRequest)editorMode(true);
    try { field('Status').classList.remove('maker-failed'); const accepted=await send(viewingRequest?'revise':'generate', { ...recipe(), request_id:viewingRequest?.request_id, original_name:viewingRequest?.name, entity:viewingRequest?.edit_target?.id, job:viewingRequest?.edit_target?.job, name:labelText(field('Name').value.trim())||template().id });if(accepted){viewingRequest=null;dialog.close();} }
    finally { field('Generate').disabled = false; }
  } };
  field('Stop').onclick = () => send('stop', {});
})();
