let particleChoices = { entrance: [], exit: [], text: [] };
let particlePreviewController = null, particlePreviewUrl = null, particlePreviewTimer = null;
let currentParticleSample = null, particleBrowserPhase = 'entrance';
let particlePreviewControlsBound=false;
const textMotionChoices = [
 {id:'directed',name:'Scene-directed motion',family:'word motion',description:'Scene-directed pushes, drops, zooms; varied editorial energy.'},
 {id:'highlight',name:'Word highlighting',family:'word motion',description:'Accent each sung word; clear, restrained emphasis.'},
 {id:'karaoke',name:'Timed left-to-right highlighting',family:'word motion',description:'Highlight across each word; precise, readable vocal timing.'},
 {id:'slide',name:'Sliding words',family:'word motion',description:'Slide words into place; smooth directional momentum.'},
 {id:'fade',name:'Fading words',family:'word motion',description:'Fade words gently; quiet, reflective, restrained atmosphere.'},
 {id:'none',name:'Clean text',family:'word motion',description:'Clean text; stillness and maximum readability.'}
];
const particleDescriptions = {
  glass: 'Crack, eject larger shards, then split into smaller, faster-spinning splinters.',
  dust: 'Fine grains drift away in a soft, turbulent cloud.',
  sparks: 'Bright hot streaks shoot out and leave glowing trails.',
  ribbons: 'Long strips curl, flutter and unravel from the letters.',
  pixels: 'Square blocks snap into a stepped digital pattern.',
  petals: 'Soft leaf-shaped pieces flutter and turn in the air.',
  snow: 'Six-point crystals drift and spin like a light flurry.',
  smoke: 'Soft expanding puffs curl and dissolve into haze.',
  bubbles: 'Translucent rings rise with small reflective highlights.',
  ink: 'Round droplets stretch, fall and splash apart.',
  vortex: 'Luminous particles spiral along an orbital flow.',
  letters: 'Individual letters fly in from different directions, tumble and align.',
  magnetic: 'Metallic chips align and move along a narrow field.'
};

function selectedParticlePool(phase) {
  const field = $(phase + 'Pool');
  if (!field?.value) return particleChoices[phase].map(effect => effect.id);
  try { const value = JSON.parse(field.value); return Array.isArray(value) ? value : []; }
  catch { return []; }
}

function restoreParticlePools(settings) {
  for (const phase of ['entrance', 'exit', 'text']) {
    let value = settings[phase + '_pool'];
    if (typeof value === 'string') { try { value = JSON.parse(value); } catch { value = null; } }
    const known = new Set(particleChoices[phase].map(effect => effect.id));
    const selected = new Set(Array.isArray(value) ? value.filter(id => known.has(id)) : known);
    $(phase + 'Pool').value = JSON.stringify([...selected]);
    document.querySelectorAll(`[data-particle-pool="${phase}"] input`).forEach(el => { el.checked = selected.has(el.value); });
    updateParticlePoolCount(phase);
  }
}

function updateParticlePoolCount(phase) {
  $(phase + 'PoolCount').textContent = `${selectedParticlePool(phase).length} in mixed set`;
  filterParticleList(phase);
}

function changeParticlePool(phase) {
  const selected = [...document.querySelectorAll(`[data-particle-pool="${phase}"] input:checked`)].map(el => el.value);
  $(phase + 'Pool').value = JSON.stringify(selected);
  const selector=$(phase==='text'?'textAnimation':phase+'Effect');
  if(!(phase==='text'&&selector.value==='ai'))selector.value='mixed';
  updateParticlePoolCount(phase);
  refreshSidebarLabels();
}

function filterParticleList(phase) {
  const query = $(phase + 'Search')?.value.toLowerCase().trim() || '';
  const family = $(phase + 'Family')?.value || '';
  const selectedOnly = $(phase + 'SelectedOnly')?.checked;
  let count = 0;
  for (const row of $(phase + 'PoolList')?.children || []) {
    const matches = row.dataset.search.includes(query) && (!family || row.dataset.family === family)
      && (!selectedOnly || row.querySelector('input').checked);
    row.hidden = !matches;
    if (matches) count++;
  }
  if ($(phase + 'ResultCount')) $(phase + 'ResultCount').textContent = phase === 'text' ? `${count} word treatments` : `${count} effects · ${selectedParticlePool(phase).length} selected for mixed`;
}

function openEffectBrowser(phase) {
  const dialog = $('effectBrowser');
  particleBrowserPhase = phase;
  for (const candidate of ['entrance', 'exit', 'text']) {
    $(candidate + 'Browser').hidden = candidate !== phase;
    $(candidate + 'Tab').setAttribute('aria-selected', String(candidate === phase));
    $(candidate + 'Tab').tabIndex = candidate === phase ? 0 : -1;
  }
  if (!dialog.open) dialog.showModal();
  const chosen = phase === 'text' ? $('textAnimation').value : $(phase + 'Effect').value;
  const id = particleChoices[phase].some(effect => effect.id === chosen) ? chosen
    : (phase === 'text' ? selectedParticlePool('text')[0]||'directed' : selectedParticlePool(phase)[0] || particleChoices[phase][0]?.id);
  if(phase==='text')refreshWordSamples();
  if (id) showParticleSample(phase, id);
  $(phase + 'Search').focus({ preventScroll: true });
}

function initParticleEffects(cfg) {
  if(!particlePreviewControlsBound){
    for(const id of ['fontFamily','fontStyle','fontScale'])$(id).addEventListener('input',()=>{
      $('fontScaleValue').value=Math.round(+$('fontScale').value*100)+'%';
      if($('effectBrowser').open){refreshWordSamples();if(currentParticleSample)showParticleSample(...currentParticleSample);}
    });
    particlePreviewControlsBound=true;
    const speed=document.createElement('div');speed.id='particlePreviewSpeedControl';speed.className='effect-preview-speed';
    speed.innerHTML='<label for="particlePreviewSpeed">Speed for this effect <output id="particlePreviewSpeedValue"></output></label><input id="particlePreviewSpeed" type="range" min="0.2" max="3" step="0.1" value="1"><button type="button" id="particlePreviewSpeedReset">Use global speed</button>';
    $('particleSampleDescription').after(speed);
    $('particlePreviewSpeed').addEventListener('input',()=>{
      if(!currentParticleSample)return;
      const speeds=effectSpeeds();speeds[currentParticleSample[1]]=+$('particlePreviewSpeed').value;
      $('effectSpeeds').value=JSON.stringify(speeds);
      showParticleSample(...currentParticleSample);
    });
    $('particlePreviewSpeedReset').addEventListener('click',()=>{
      if(!currentParticleSample)return;
      const speeds=effectSpeeds();delete speeds[currentParticleSample[1]];
      $('effectSpeeds').value=JSON.stringify(speeds);
      showParticleSample(...currentParticleSample);
    });
    for(const id of ['particleSpeed','particleIntensity'])$(id).addEventListener('input',()=>{
      if($('effectBrowser').open && currentParticleSample && currentParticleSample[0])showParticleSample(...currentParticleSample);
    });
  }
  window.aiTypographyAvailable=!!cfg.ai_typography_supported;
  const aiOption=$('textAnimation').querySelector('option[value=ai]');
  if(aiOption)aiOption.disabled=!window.aiTypographyAvailable;
  if(!window.aiTypographyAvailable&&$('textAnimation').value==='ai')$('textAnimation').value='mixed';
  particleChoices.text = textMotionChoices;
  $('textAnimation').disabled = !cfg.word_animations_supported;
  $('browseText').disabled = !cfg.word_animations_supported;
  $('textTab').disabled = !cfg.word_animations_supported;
  $('autoAccept').disabled = !cfg.auto_accept_supported;
  const pendingUpdates=[];
  if((cfg.particle_materials_version||0)<13)pendingUpdates.push('new effects');
  if((cfg.video_history_version||0)<2)pendingUpdates.push('complete video history');
  let note=$('interfaceUpdateNote');
  if(pendingUpdates.length){
    if(!note){note=document.createElement('p');note.id='interfaceUpdateNote';note.className='compatibility-note';$('studioCompatibility').append(note);}
    note.textContent='To load '+pendingUpdates.join(' and ')+', restart Studio after the current generation finishes. The live gallery works now.';
  }else note?.remove();
  for (const phase of ['entrance', 'exit']) {
    const el = $(phase + 'Effect');
    if (!el) continue;
    const saved = el.value;
    particleChoices[phase] = cfg.particle_effects?.[phase] || [];
    el.replaceChildren(new Option('From saved profile', 'legacy'), new Option('Mixed selected effects', 'mixed'), new Option('None', 'none'));
    for (const effect of particleChoices[phase]) el.add(new Option(effect.name, effect.id));
    el.value = [...el.options].some(option => option.value === saved) ? saved : 'none';
    const list = $(phase + 'PoolList');
    list.replaceChildren();
    const family = $(phase + 'Family');
    family.replaceChildren(new Option('All families', ''));
    for (const name of [...new Set(particleChoices[phase].map(effect => effect.family))]) {
      family.add(new Option(name==='cinematic'?'Cinematic particles':name==='trees'?'Trees':name==='flock'?'Birds & bats':name==='ornament'?'Ornamental growth':name==='petals'?'Petals & leaves':name[0].toUpperCase() + name.slice(1), name));
    }
    for (const effect of particleChoices[phase]) {
      const row = document.createElement('div');
      row.className = 'particle-choice';
      row.dataset.search = (effect.name + ' ' + effect.family + ' ' + (effect.description || '')).toLowerCase();
      row.dataset.family = effect.family;
      row.dataset.effect = effect.id;
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.value = effect.id; checkbox.checked = true;
      checkbox.setAttribute('aria-label', 'Include ' + effect.name + ' in mixed ' + phase + 's');
      checkbox.onchange = () => { changeParticlePool(phase); showParticleSample(phase, effect.id); };
      const preview = document.createElement('button');
      preview.type = 'button'; preview.className = 'particle-preset';
      preview.setAttribute('aria-label', 'Preview ' + effect.name + ' ' + phase);
      const title = document.createElement('span'); title.textContent = effect.name;
      const detail = document.createElement('small'); detail.textContent = effect.description || effect.family;
      if (effect.base_color && effect.base_color !== 'ink') {
        const swatch = document.createElement('span'); swatch.className = 'base-swatch';
        swatch.style.background = effect.base_color; swatch.title = 'Base colour ' + effect.base_color;
        detail.prepend(swatch);
      }
      preview.append(title, detail);
      preview.onclick = () => showParticleSample(phase, effect.id);
      row.append(checkbox, preview); list.append(row);
    }
    $(phase + 'Pool').value = JSON.stringify(particleChoices[phase].map(effect => effect.id));
    updateParticlePoolCount(phase);
    for (const suffix of ['Search', 'Family', 'SelectedOnly']) {
      $(phase + suffix).addEventListener(suffix === 'Search' ? 'input' : 'change', () => filterParticleList(phase));
    }
    for (const [suffix, checked] of [['All', true], ['None', false]]) {
      $(phase + suffix).onclick = () => {
        list.querySelectorAll('input').forEach(input => { input.checked = checked; });
        changeParticlePool(phase);
      };
    }
    $(phase + 'Tab').onclick = () => openEffectBrowser(phase);
    el.onchange = () => {
      refreshSidebarLabels();
      if (particleChoices[phase].some(effect => effect.id === el.value)) openEffectBrowser(phase);
    };
  }
  const textList = $('textPoolList'); textList.replaceChildren();
  for (const effect of textMotionChoices) {
    const row = document.createElement('div');row.className='particle-choice text-choice';row.dataset.search=effect.name.toLowerCase();row.dataset.effect=effect.id;
    row.dataset.particlePool='text';
    const check=document.createElement('input');check.type='checkbox';check.value=effect.id;check.checked=true;
    check.setAttribute('aria-label','Include '+effect.name+' in mixed word animations');
    check.onchange=()=>{changeParticlePool('text');showParticleSample('text',effect.id);};
    const button=document.createElement('button');button.type='button';button.className='particle-preset';
    const title=document.createElement('span');title.textContent=effect.name;
    const thumb=document.createElement('img');thumb.className='word-motion-thumbnail';thumb.loading='lazy';thumb.alt=effect.name+' animated sample';thumb.dataset.animation=effect.id;
    button.append(title,thumb);button.onclick=()=>showParticleSample('text',effect.id);
    row.append(check,button);textList.append(row);
  }
  $('textPool').value=JSON.stringify(textMotionChoices.map(choice=>choice.id));updateParticlePoolCount('text');
  for(const [id,checked] of [['textAll',true],['textNone',false]])$(id).onclick=()=>{textList.querySelectorAll('input').forEach(input=>input.checked=checked);changeParticlePool('text');};
  $('textSearch').oninput=()=>filterParticleList('text');filterParticleList('text');
  $('textTab').onclick=()=>openEffectBrowser('text');
  $('browseText').onclick=()=>openEffectBrowser('text');
  $('textAnimation').onchange=()=>openEffectBrowser('text');
  $('browseEntrance').onclick = () => openEffectBrowser('entrance');
  $('browseExit').onclick = () => openEffectBrowser('exit');
  $('closeEffectBrowser').onclick = () => $('effectBrowser').close();
  $('effectBrowser').onclose = () => { particlePreviewController?.abort(); clearTimeout(particlePreviewTimer); };
  $('replayParticle').onclick = () => { if (currentParticleSample) showParticleSample(...currentParticleSample); };
  $('useParticleEffect').onclick = () => {
    if (!currentParticleSample) return;
    const [phase, id] = currentParticleSample;
    (phase === 'text' ? $('textAnimation') : $(phase + 'Effect')).value = id;
    $('particleSelectionHint').textContent = `${particleChoices[phase].find(effect => effect.id === id)?.name || id} applied to ${phase}.`;
    refreshSidebarLabels();
  };
  initializeStudioLayout();
  refreshTypographyLabels();
}

function showParticleSample(phase, id) {
  clearTimeout(particlePreviewTimer);
  particlePreviewController?.abort();
  const effect = particleChoices[phase].find(item => item.id === id);
  if (!effect) return;
  currentParticleSample = [phase, id];
  if($('particlePreviewSpeedControl')){ const own=effectSpeeds()[id];const value=own??+$('particleSpeed').value;$('particlePreviewSpeedControl').hidden=false;$('particlePreviewSpeed').value=value;$('particlePreviewSpeedValue').value=Number(value).toFixed(1)+'×'+(own==null?' (global)':''); }
  const controller = particlePreviewController = new AbortController();
  $('particleSampleTitle').textContent = effect.name;
  $('particleSamplePhase').textContent = phase + ' / ' + effect.family;
  const growthHelp={'old-oak-lettering':'Deeply fissured oak bark forms the letters, with gnarled branches, lobed leaves and tiny acorns.','autumn-maple-lettering':'Woody trunks branch into delicate maple canopies in green, amber, orange and crimson.','clockwork-lettering':'Interlocking brass and steel gears rotate into place with teeth, spokes and tiny polished axles.','folded-paper-lettering':'Layered colored paper facets unfold into sculpted letters with crisp folds and shaded edges.','obsidian-lattice-lettering':'Dark obsidian facets and angular violet wireframes assemble into abstract geometric letters.','birds-flocking-lettering':'Wing-animated birds approach real ink anchors in every character, then settle without hiding the text.','bats-flocking-lettering':'Membrane-winged bats bank toward every character and settle around its strokes.','gold-filigree-lettering':'Fine gold scrolls unfurl into mirrored filigree, beaded borders and raised metal curls.','pearl-lace-lettering':'Interlaced ivory loops, tiny picot stitches and pearl knots weave each word.','jeweled-brocade-lettering':'Gold paisley embroidery and faceted ruby, emerald and sapphire settings form a rich brocade.','luminous-coral-lettering':'Branching sea fans, fine coral filaments and luminous polyps grow from each letter.','frost-crystal-lettering':'Ice facets and branching frost crystallize from each sung word.','ink-bloom-lettering':'Watercolor pigment spreads through each sung word in soft pools.','thread-stitch-lettering':'Gold and turquoise thread stitches each sung word into place.'};
  $('particleSampleDescription').textContent = effect.description || growthHelp[id] || (effect.hold === 'particles' ? 'Large overlapping leaves fill each letter. Small flowers and petals grow with depth-aware vines on the sung word.' : particleDescriptions[effect.family]) || '';
  $('particleSampleStatus').textContent = 'Rendering preview…';
  $('particleSampleImage').hidden = true;
  $('particleSampleLoading').hidden = false;
  $('replayParticle').disabled = true;
  $('useParticleEffect').disabled = false;
  $('useParticleEffect').textContent = 'Use ' + effect.name;
  $('particleSelectionHint').textContent = 'Use this effect to apply one preset, or check presets for mixed mode.';
  for (const row of $(phase + 'PoolList').children) {
    row.classList.toggle('is-previewing', row.dataset.effect === id);
  }
  particlePreviewTimer = setTimeout(async () => {
    try {
      const query = sampleQuery(phase,id);
      const response = await fetch('/api/particle-preview?' + query, { signal: controller.signal });
      if (!response.ok) { const result = await response.json(); throw Error(result.error || 'Preview failed'); }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const sample = $('particleSampleImage');
      sample.src = url; sample.alt = effect.name + ' ' + phase + ' animation';
      await sample.decode();
      if (controller.signal.aborted) { URL.revokeObjectURL(url); return; }
      if (particlePreviewUrl) URL.revokeObjectURL(particlePreviewUrl);
      particlePreviewUrl = url;
      sample.hidden = false;
      $('particleSampleStatus').textContent = effect.name + ' / ' + phase + ' · ' + $('particleSpeed').value + '×';
    } catch (error) {
      if (!controller.signal.aborted) $('particleSampleStatus').textContent = error.message;
    } finally {
      if (particlePreviewController === controller) {
        $('particleSampleLoading').hidden = true;
        $('replayParticle').disabled = false;
      }
    }
  }, 250);
}

let studioLayoutInitialized = false;
const selectCaptions = new WeakMap();
function refreshSidebarLabels() {
  if ($('reviewModeHelp') && $('autoAccept')) $('reviewModeHelp').textContent = $('autoAccept').disabled ? 'Restart Studio after the current job to enable auto-accept.' : $('autoAccept').checked ? 'Continue straight to rendering without manual approval. Automatic validation is configured separately.' : 'Pause for manual artwork approval before rendering. Automatic validation is configured separately.';
  const canvas = document.createElement('canvas');
  const measure = canvas.getContext('2d');
  document.querySelectorAll('aside select:not([hidden])').forEach(select => {
    let caption = selectCaptions.get(select);
    if (!caption) {
      caption = document.createElement('small'); caption.className = 'selected-value';
      select.after(caption); selectCaptions.set(select, caption);
    }
    const text = select.selectedOptions[0]?.textContent || '';
    measure.font = getComputedStyle(select).font;
    select.title = text; caption.textContent = text;
    caption.hidden = select.clientWidth === 0 || measure.measureText(text).width <= select.clientWidth - 42;
  });
}

function initializeStudioLayout() {
  if (studioLayoutInitialized) return;
  studioLayoutInitialized = true;
  const header = $('studioHeader');
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--studio-header-offset', header.offsetHeight + 30 + 'px');
  }).observe(header);
  new ResizeObserver(() => refreshSidebarLabels()).observe(document.querySelector('aside'));
  document.querySelector('aside').addEventListener('change', refreshSidebarLabels);
  document.querySelector('aside').addEventListener('toggle', refreshSidebarLabels, true);
  let queued = false;
  const update = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; refreshSidebarLabels(); });
  };
  document.querySelectorAll('aside select').forEach(select => {
    new MutationObserver(update).observe(select, { childList: true, subtree: true });
  });
  update();
}

let rebuildNotice = { job: null, signature: '', dismissed: '', forced: false, video: '' };
let videoHistoryJob = null, selectedVideoVersion = 'current', videoHistorySignature = '';
const localVideoChanges = new Map();

function recordRebuildAction(operation, args) {
  if (!state?.video || !['select', 'replace'].includes(operation)) return;
  const index = Number(args instanceof FormData ? args.get('index') : args.index);
  if (!Number.isInteger(index)) return;
  if (!localVideoChanges.has(jobId)) localVideoChanges.set(jobId, new Set());
  localVideoChanges.get(jobId).add(index);
}

function initializeVideoControls() {
  $('showRebuild').onclick = () => { rebuildNotice.forced = true; if (state) updateRebuildNotice(state); };
  const hide = () => {
    rebuildNotice.dismissed = rebuildNotice.signature;
    rebuildNotice.forced = false;
    try { sessionStorage.setItem('kineticRebuildDismissed:' + jobId, rebuildNotice.dismissed); } catch {}
    if (state) updateRebuildNotice(state);
  };
  $('minimizeRebuild').onclick = hide;
  $('closeRebuild').onclick = hide;
  $('videoHistory').onchange = () => {
    selectedVideoVersion = $('videoHistory').value;
    if (state) updateVideoHistory(state);
  };
  $('latestVideo').onclick = () => { selectedVideoVersion = 'current'; if (state) updateVideoHistory(state); };
}

function updateRebuildNotice(s) {
  if (rebuildNotice.job !== jobId) {
    let dismissed = '';
    try { dismissed = sessionStorage.getItem('kineticRebuildDismissed:' + jobId) || ''; } catch {}
    rebuildNotice = { job: jobId, signature: '', dismissed, forced: false, video: '' };
  }
  const pending = s.dirty || [];
  const dirty = s.dirty_verified ? pending : [...(localVideoChanges.get(jobId) || [])].filter(index => pending.includes(index));
  const signature = JSON.stringify(dirty.map(index => [index,
    s.images?.find(image => image.index === index)?.variants.find(variant => variant.current)?.url || '']));
  if (rebuildNotice.video && s.video !== rebuildNotice.video) {
    rebuildNotice.forced = false;
    localVideoChanges.delete(jobId);
  }
  rebuildNotice.video = s.video || '';
  rebuildNotice.signature = signature;
  const rendering = s.action === 'patch' || s.action === 'rerender' || s.status === 'running';
  $('rebuildDock').hidden = !s.video;
  $('showRebuild').textContent = dirty.length ? `Video tools · ${dirty.length} unapplied image change${dirty.length === 1 ? '' : 's'}` : 'Video tools';
  $('showRebuild').disabled = rendering;
  $('rebuildPanel').hidden = !s.video || rendering || !rebuildNotice.forced;
  const canBuild = backendReady && !s.rejected_images?.length && s.status === 'complete' && !s.action && !s.queued_actions?.length;
  $('rebuildImages').disabled = !canBuild || !pending.length;
  $('rebuildEffects').disabled = !canBuild;
  $('rebuildTitle').textContent = 'Video tools';
  $('rebuildMessage').textContent = s.rejected_images?.length
    ? 'Review or regenerate images below the quality threshold before rebuilding.'
    : dirty.length ? 'The image is ready. Rebuild the affected section to include it in the exported video.'
    : 'Apply the selected word animation and particle effects to a new export.';
}

function updateVideoHistory(s) {
  if (videoHistoryJob !== jobId) {
    videoHistoryJob = jobId; selectedVideoVersion = 'current'; videoHistorySignature = '';
  }
  const versions = Array.isArray(s.video_versions) ? s.video_versions
    : s.video ? [{ id: 'current', url: s.video, current: true, name: 'video.mp4' }] : [];
  if (!versions.length) { $('videoPanel').style.display = 'none'; return; }
  const signature = JSON.stringify(versions.map(version => [version.id, version.url]));
  if (signature !== videoHistorySignature) {
    $('videoHistory').replaceChildren(...versions.map((version, index) => {
      const stamp = version.modified ? new Date(version.modified * 1000).toLocaleString() : '';
      return new Option(version.current ? 'Current export' : `Previous export ${index+(versions[0]?.current?0:1)} · ${stamp}`, version.id);
    }));
    videoHistorySignature = signature;
  }
  const selected = versions.find(version => version.id === selectedVideoVersion) || versions[0];
  selectedVideoVersion = selected.id;
  $('videoHistory').value = selected.id;
  $('videoHistory').disabled = versions.length < 2;
  $('latestVideo').hidden = selected.current;
  $('videoVersionInfo').textContent = selected.current ? 'Watching the current export.'
    : 'Watching a saved export. The current video and selected images are unchanged.';
  if (!Array.isArray(s.video_versions)) $('videoVersionInfo').textContent += ' Restart Studio after the current job to load video history.';
  if (selected.url !== videoUrl) {
    $('video').pause();
    videoUrl = selected.url; $('video').src = selected.url;
    if (selected.current && s.poster) $('video').poster = s.poster;
    else $('video').removeAttribute('poster');
  }
  $('download').href = selected.url;
  $('download').download = selected.name || 'lyric-video.mp4';
  $('videoPanel').style.display = 'block';
}

function refreshTypographyLabels(){
  if($('fontScaleValue'))$('fontScaleValue').value=Math.round(+$('fontScale').value*100)+'%';
}
function effectSpeeds(){try{return JSON.parse($('effectSpeeds')?.value||'{}')||{}}catch{return {}}}
function sampleQuery(phase,id){
  return new URLSearchParams({phase,effect:id,intensity:$('particleIntensity').value,speed:(phase==='text'?null:effectSpeeds()[id])??$('particleSpeed').value,
    font_family:$('fontFamily').value,font_style:$('fontStyle').value,font_scale:$('fontScale').value,v:'word-materials-14'});
}
function refreshWordSamples(){
  document.querySelectorAll('.word-motion-thumbnail').forEach(img=>{img.src='/api/particle-preview?'+sampleQuery('text',img.dataset.animation);});
}

async function hydrateLiveArtwork(snapshot,project){
  if(snapshot.images?.some(image=>image.variants?.length))return snapshot;
  try{
    const response=await fetch('/files/'+encodeURIComponent(project)+'/live-artwork.json?t='+Date.now(),{cache:'no-store'});
    if(!response.ok)return snapshot;
    let data=await response.json();
    const previous=(data.previous_attempt&&data.ready>0)||(!data.ready&&data.previous?.ready);
    if(!data.ready&&data.previous?.ready)data=data.previous;
    if(!data.images?.length)return snapshot;
    snapshot.images=data.images.map(image=>({...image,variants:image.variants.map(variant=>({...variant,
      url:'/files/'+encodeURIComponent(project)+'/'+variant.path.split('/').map(encodeURIComponent).join('/')+'?v='+variant.modified}))}));
    snapshot.artwork_notice=previous?'Saved artwork from the previous attempt. New images will appear as the current run finishes them.':'';
  }catch{}
  return snapshot;
}
