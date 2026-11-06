let gpuModelCatalog=null;
const QWEN_IMAGE_DEFAULT='Qwen/Qwen-Image-2.1';
function addModelOption(select,id,label){if(![...select.options].some(o=>o.value===id))select.add(new Option(label||id,id))}
function isCodingModel(name){return /coder|codellama|codestral|code-/i.test(name||'')}
function isVisionModel(name){
 const normalized=value=>(value||'').toLowerCase().replace(/:latest$/,'');
 const prompting=(gpuModelCatalog?.prompt_models||[]).some(value=>normalized(value)===normalized(name));
 if(prompting)return false;
 const known=[...(gpuModelCatalog?.vision_models||[]),...(gpuModelCatalog?.vision_choices||[]).map(m=>m.id)];
 return /^qwen[^:]*-vl(?=:|$)/i.test(name||'')||known.some(value=>normalized(value)===normalized(name));
}
function promptingModelSelection(name){return !name||isCodingModel(name)||isVisionModel(name)?'auto':name}
function showModelPlan(message){const el=$('modelPlan');if(el)el.textContent=message}
function installModelChoices(catalog){
 gpuModelCatalog=catalog;
 const previousPrompt=$('aiModel').value;
 const previousVision=preferredVisionModel??$('visionModel').value;
 $('aiModel').replaceChildren(new Option('Auto · GPU-fit text model','auto'));
 const installedPrompts=new Set(catalog.prompt_models||[]);
 for(const m of catalog.prompt_choices||[])addModelOption($('aiModel'),m.id,m.name+(m.installed===false?' · download required':''));
 for(const name of installedPrompts)if(!isCodingModel(name)&&!isVisionModel(name))addModelOption($('aiModel'),name);
 const prompt=promptingModelSelection(previousPrompt);
 addModelOption($('aiModel'),prompt);$('aiModel').value=prompt;
 const visions=catalog.vision_models||catalog.models||[];
 $('visionModel').replaceChildren(new Option('Choose a validation model',''));
 for(const m of catalog.vision_choices||[])addModelOption($('visionModel'),m.id,m.name+(m.installed===false?' · download required':''));
 for(const name of visions)if(!isCodingModel(name))addModelOption($('visionModel'),name);
 const vision=previousVision&&!isCodingModel(previousVision)?previousVision:(catalog.default_model||'');
 if(vision)addModelOption($('visionModel'),vision);$('visionModel').value=vision;preferredVisionModel=vision;
 scheduleModelDownloads();
 if(catalog.gpu){const g=catalog.gpu;showModelPlan(`${g.name} · ${(g.total_bytes/2**30).toFixed(1)} GiB total · ${(g.free_bytes/2**30).toFixed(1)} GiB free. Prompting runs first; generation and validation run in complete batches.`)}
 gallerySignature='';if(state)renderGallery(state);
}
function applyGpuPreset(preset,catalog){
 if(!preset)throw Error(catalog?.message||'No GPU-only combination fits the available VRAM.');
 for(const [id,key] of [['aiModel','ai_model'],['imageModel','image_model'],['visionModel','vision_model']]){
  addModelOption($(id),preset[key]);$(id).value=preset[key];
 }
 preferredVisionModel=preset.vision_model;
 const image=imageModels.find(m=>m.id===preset.image_model);if(image)$('steps').value=image.steps;
 $('gpuPreset').value=String(preset.vram_gib);modelHelp();
 const missing=preset.missing||[preset.ai_model,...($('autoVerify').checked?[preset.vision_model]:[])].filter(name=>!(catalog?.prompt_models||[]).includes(name)&&!(catalog?.vision_models||[]).includes(name));
 const gpu=preset.gpu_name?`${preset.gpu_name} · ${preset.available_gib} GiB usable. `:'';
 showModelPlan(gpu+`${preset.ai_model} → ${image?.name||preset.image_model} → ${preset.vision_model}. `+(!$('autoVerify').checked?'Validation is off. Image generation can use the full GPU budget. ':preset.co_resident===true?'Image and validation weights can stay resident together. ':'Generation and validation switch only after each full batch. ')+(missing.length?'Missing models will download automatically. ':''));
 scheduleModelDownloads();
 renderProductionStages(state);
 gallerySignature='';if(state)renderGallery(state);
}
function setupModelControls(cfg){
 gpuModelCatalog={...(gpuModelCatalog||{}),presets:cfg.model_presets||[],prompt_choices:cfg.prompt_choices||[],vision_choices:cfg.vision_choices||[]};
 for(const m of cfg.prompt_choices||[])addModelOption($('aiModel'),m.id,m.name);
 for(const m of cfg.vision_choices||[])addModelOption($('visionModel'),m.id,m.name);
 $('gpuPreset').onchange=()=>{if(!$('gpuPreset').value)return;try{applyGpuPreset((gpuModelCatalog?.presets||[]).find(p=>p.vram_gib===+$('gpuPreset').value),gpuModelCatalog)}catch(e){toast(e.message)}};
 $('bestModels').onclick=async()=>{
  const button=$('bestModels');button.disabled=true;button.textContent='Detecting…';
  try{
   if(['running','queued','review'].includes(state?.status)||state?.action)throw Error('Choose models after the active job finishes.');
   const catalog=await api('/api/models/best?review='+($('autoVerify').checked?'1':'0'));if(!catalog.recommendation)throw Error(catalog.message||'No GPU-only combination fits the available VRAM.');installModelChoices(catalog);applyGpuPreset(catalog.recommendation,catalog);
  }catch(e){showModelPlan(e.message);toast(e.message)}finally{button.disabled=false;button.textContent='Best'}
 };
 syncValidationControls();
 $('autoVerify').addEventListener('change',()=>{syncValidationControls();$('gpuPreset').value='';scheduleModelDownloads()});
 // the reference check's settings follow its toggle, as the image review's do
 const syncReferenceReview=()=>{if($('repaintReferences')&&$('reviewReferences'))$('repaintReferences').disabled=!$('reviewReferences').checked};
 $('reviewReferences')?.addEventListener('change',syncReferenceReview);syncReferenceReview();
 startGpuMonitor();
 $('cache').addEventListener('change',scheduleModelDownloads);
 $('aiModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads()});
 $('visionModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads()});
 $('imageModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads();renderProductionStages(state)});
 if($('rollSeed')){
  $('rollSeed').onclick=()=>{
   $('imageSeed').value=Math.floor(Math.random()*2147483647);
   $('randomizeSeed').checked=false;
  };
  $('imageSeed').oninput=()=>{
   if($('imageSeed').value.trim()!==''){
    $('randomizeSeed').checked=false;
   }else{
    $('randomizeSeed').checked=true;
   }
  };
  $('randomizeSeed').onchange=()=>{
   if($('randomizeSeed').checked){
    $('imageSeed').value='';
    $('imageSeed').placeholder='Random per image';
   }else if(!$('imageSeed').value.trim()){
    $('imageSeed').value=Math.floor(Math.random()*2147483647);
   }
  };
 }
}


let gpuMonitorStarted=false,downloadTimer=null,downloadSelectionKey='',downloadIds=[],downloadRequest=null,downloadPoll=null,downloadSnapshot=[];
function gib(bytes){return (bytes/2**30).toFixed(1)+' GiB'}
function node(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el}
async function refreshGpuUsage(){
 if(document.hidden)return;
 try{
  const data=await api('/api/gpu');const host=$('gpuMemoryCards');host.replaceChildren();
  renderHeaderGpu(data.gpus||[]);
  if(!data.gpus?.length){host.append(node('div','help','GPU memory information is unavailable.'));return}
  for(const gpu of data.gpus){
   const card=node('div','gpu-memory-card');card.append(node('div','gpu-memory-name',gpu.name),node('div','gpu-memory-summary',gib(gpu.free_bytes)+' free / '+gib(gpu.total_bytes)+' total'));
   const bar=node('div','vram-blocks');bar.setAttribute('role','img');bar.setAttribute('aria-label',gpu.blocks.map(b=>b.label+' '+gib(b.bytes)).join(', '));
   const legend=node('div','vram-legend');
   gpu.blocks.forEach((block,i)=>{
    const part=node('div','vram-block vram-'+block.kind);part.style.width=(100*block.bytes/gpu.total_bytes)+'%';part.title=block.label+' · '+gib(block.bytes);bar.append(part);
    const row=node('div','vram-key');row.append(node('span','vram-swatch vram-'+block.kind),node('span','vram-label',block.label),node('span','vram-value',gib(block.bytes)));legend.append(row);
   });
   card.append(bar,legend);host.append(card);
  }
 }catch(e){$('gpuMemoryCards').replaceChildren(node('div','help','GPU monitor unavailable: '+e.message));$('headerGpu')?.replaceChildren(node('div','help','GPU monitor unavailable'))}
}
// One colour per model (studio-tokens.css), shared by the GPU map and the model list: a role's colour goes to its model,
// so a model chosen for two roles keeps one colour on both pills, and a loaded model the list does not name takes the extra.
const MODEL_PILLS={asr:'headerAsrModel',timing:'headerTimingModel',text:'headerTextModel',image:'headerSelectedImage',vision:'headerVisionModel',video:'headerVideoModel',end:'headerEndModel'};
let extraModel='';
// A chosen id against a block's name: an estimated block names the repository's last part, Ollama may leave out :latest
const modelKey=name=>String(name).replace(/:latest$/,'').split('/').pop();
const sameModel=(a,b)=>!!a&&!!b&&modelKey(a)===modelKey(b);
const blockNames=block=>block.models||block.label.replace(/ \(estimate.*$/,'').split(', ');
// What paints the end frames for the next run, '' when none do (see video_generation.step.image_model_of).
function endFrameModel(){return '';}
function chosenModels(){
 const value=id=>$(id)?.value||'',text=value('aiModel');
 return {asr:value('asrModel'),timing:value('alignmentModel'),text:text==='auto'?autoTextModel:text,image:value('imageModel'),vision:value('visionModel'),video:value('videoModel'),end:endFrameModel()};
}
function syncModelColours(){
 const chosen=chosenModels(),roles=Object.keys(MODEL_PILLS);
 for(const role of roles){const pill=$(MODEL_PILLS[role]);if(pill)pill.dataset.role=roles.find(r=>sameModel(chosen[r],chosen[role]))||role}
}
// A block is the model chosen now, or the one the open project ran with.
function blockRole(block){
 const saved=(typeof state!=='undefined'&&state?.production_models)||{},chosen=chosenModels();
 const used={asr:saved.asr,timing:saved.alignment,text:saved.prompt,image:saved.image,vision:saved.vision,video:saved.video};
 const names=blockNames(block);
 const role=Object.keys(chosen).find(r=>names.some(name=>sameModel(chosen[r],name)||sameModel(used[r],name)));
 if(role)return role;
 if(!['ollama','image'].includes(block.kind))return '';
 extraModel||=names[0];return extraModel===names[0]?'extra':'';
}
// A model in the map is loaded, so its pill says so: the two never disagree, whatever the readiness check knows.
let mapRoles=new Set();
function showMapLoaded(){
 for(const role of mapRoles)for(const pill of document.querySelectorAll(`.header-models>span[data-role="${role}"]`)){pill.dataset.state='loaded';pill.dataset.note=READINESS_NOTES.loaded}
}
function setMapRoles(roles){
 for(const role of mapRoles)if(!roles.has(role))for(const pill of document.querySelectorAll(`.header-models>span[data-role="${role}"]`)){pill.dataset.state='ready';pill.dataset.note=READINESS_NOTES.ready}
 mapRoles=roles;showMapLoaded();
}
// The header's map: one bar a GPU, a block a model, named on hover. Parts are updated in place, so a hover survives each refresh.
function renderHeaderGpu(gpus){
 const host=$('headerGpu');if(!host)return;
 if(!gpus.length){host.replaceChildren(node('div','help','GPU memory information is unavailable.'));return}
 if(host.querySelectorAll('.gpu-diagram').length!==gpus.length)host.replaceChildren(...gpus.map(()=>{
  const card=node('div','gpu-diagram'),head=node('div','gpu-diagram-head'),bar=node('div','gpu-diagram-bar');bar.setAttribute('role','img');
  head.append(node('span','gpu-diagram-name'),node('span','gpu-diagram-total'));card.append(head,bar);return card}));
 if(!gpus.some(gpu=>gpu.blocks.some(block=>blockNames(block).includes(extraModel))))extraModel='';
 const roles=new Set();
 gpus.forEach((gpu,i)=>{
  const card=host.children[i],bar=card.querySelector('.gpu-diagram-bar');
  card.querySelector('.gpu-diagram-name').textContent=gpu.name.replace(/^NVIDIA\s+(GeForce\s+)?/,'');
  card.querySelector('.gpu-diagram-total').textContent=gib(gpu.used_bytes)+' used of '+gib(gpu.total_bytes);
  bar.setAttribute('aria-label',gpu.blocks.map(b=>b.label+' '+gib(b.bytes)).join(', '));
  while(bar.children.length<gpu.blocks.length)bar.append(node('div','gpu-part'));
  while(bar.children.length>gpu.blocks.length)bar.lastChild.remove();
  gpu.blocks.forEach((block,k)=>{
   const role=blockRole(block),part=bar.children[k];
   if(role){part.dataset.role=role;roles.add(role)}else delete part.dataset.role;
   part.dataset.kind=block.kind;part.style.flexGrow=block.bytes;part.title=block.label+' · '+gib(block.bytes);
  });
 });
 setMapRoles(roles);
}
function startGpuMonitor(){
 if(gpuMonitorStarted)return;gpuMonitorStarted=true;refreshGpuUsage();setInterval(refreshGpuUsage,3000);
 $('retryModelDownloads').onclick=()=>beginSelectedDownloads(true).catch(e=>toast(e.message));
 $('cancelModelDownloads').onclick=async()=>{try{await api('/api/downloads/cancel',{ids:downloadIds});await refreshDownloadStatus()}catch(e){toast(e.message)}};
}
function selectedDownloadSpecs(){
 const prompt=$('aiModel').value==='auto'?gpuModelCatalog?.default_prompt_model:$('aiModel').value;
 const specs=[];
 if(prompt)specs.push({kind:'ollama',model:prompt});
 if($('autoVerify').checked&&$('visionModel').value)specs.push({kind:'ollama',model:$('visionModel').value});
 if($('imageModel').value)specs.push({kind:'image',model:$('imageModel').value,cache:$('cache').value});
 return specs.filter((value,index,all)=>all.findIndex(other=>other.kind===value.kind&&other.model===value.model)===index);
}
function showDownloads(tasks){
 downloadSnapshot=tasks;renderProductionHeader(state);
 const host=$('modelDownloadList');host.replaceChildren();
 const active=tasks.some(t=>['queued','downloading'].includes(t.status));$('cancelModelDownloads').hidden=!active;$('retryModelDownloads').hidden=!tasks.some(t=>['failed','cancelled'].includes(t.status));
 for(const task of tasks){
  const card=node('div','download-card');card.append(node('div','download-model',task.model),node('div','download-message',task.error||task.message||task.status));
  const bar=node('progress','download-progress');bar.max=100;if(task.percent!==null&&task.percent!==undefined)bar.value=task.percent;bar.setAttribute('aria-label',task.model+' download progress');card.append(bar);
  let detail=task.status==='complete'?'Ready':task.percent===null?'Waiting…':task.percent+'%';
  if(task.total)detail+=' · '+(task.unit==='files'?task.completed+' / '+task.total+' files':gib(task.completed)+' / '+gib(task.total));
  card.append(node('div','help',detail));if(task.status==='failed'||task.status==='cancelled')card.classList.add('download-error');host.append(card);
 }
}
async function refreshDownloadStatus(){
 const result=await api('/api/downloads');downloadSnapshot=(result.tasks||[]).filter(task=>downloadIds.includes(task.id));showDownloads(downloadSnapshot);if(downloadSnapshot.length&&downloadSnapshot.every(t=>!['queued','downloading'].includes(t.status))){clearInterval(downloadPoll);downloadPoll=null;}return downloadSnapshot;
}
async function beginSelectedDownloads(force=false){
 const specs=selectedDownloadSpecs();const key=JSON.stringify(specs);
 if(downloadRequest)return downloadRequest.then(()=>beginSelectedDownloads(force));
 if(key===downloadSelectionKey&&!force&&downloadIds.length)return downloadIds;
 downloadSelectionKey=key;
 downloadRequest=(async()=>{
  const obsolete=downloadSnapshot.filter(task=>['queued','downloading'].includes(task.status)&&!specs.some(spec=>spec.model===task.model&&spec.kind===task.kind)).map(task=>task.id);
  if(obsolete.length)await api('/api/downloads/cancel',{ids:obsolete});
  const result=await api('/api/downloads',{models:specs});downloadIds=result.ids||[];downloadSnapshot=result.tasks||[];showDownloads(downloadSnapshot);
  if(!downloadPoll)downloadPoll=setInterval(()=>{if(downloadIds.length&&!document.hidden)refreshDownloadStatus().catch(()=>{})},1000);
  return downloadIds;
 })();
 try{return await downloadRequest}finally{downloadRequest=null}
}
function scheduleModelDownloads(){
 clearTimeout(downloadTimer);
 if(['running','queued','review'].includes(state?.status)||state?.action)return;
 downloadTimer=setTimeout(()=>beginSelectedDownloads().catch(e=>{$('modelDownloadList').replaceChildren(node('div','help','Could not start downloads: '+e.message))}),900);
}
async function ensureSelectedDownloads(){
 clearTimeout(downloadTimer);
 const connection=await api('/api/config');token=connection.token;
 await beginSelectedDownloads();
 if(!downloadIds.length)throw Error('Choose the prompting, image and validation models first.');
 let recovered=0;
 while(true){
  const tasks=await refreshDownloadStatus();
  if(tasks.length!==downloadIds.length){
   if(recovered++>=2)throw Error('Could not restore model download status. Retry Generate.');
   $('uploadProgress').textContent='Restoring model download status…';
   const connection=await api('/api/config');token=connection.token;
   await beginSelectedDownloads(true);
   if(!downloadIds.length)throw Error('No model downloads were registered. Check the selected models and retry.');
   continue;
  }
  const failed=tasks.find(t=>['failed','cancelled'].includes(t.status));if(failed)throw Error(failed.error||failed.message||'Model download failed.');
  if(tasks.every(t=>t.status==='complete'))return;
  $('uploadProgress').textContent='Preparing models — download progress is shown in the left panel.';
  await new Promise(resolve=>setTimeout(resolve,750));
 }
}

function syncValidationControls(){
 const enabled=$('autoVerify').checked;
 $('visionModel').disabled=!enabled;
 $('autoRepair').disabled=!enabled;$('reviewThreshold').disabled=!enabled;
 if(!enabled)$('verifyAll').disabled=true;
 gallerySignature='';if(state)renderGallery(state);
}


let livePipelinePending=false,livePipelineSignature='',livePipelineAt=0;
function paintLivePipeline(s){
 const card=$('projectPipelineCard');if(!card)return;
 const mapping={alignment:1,subjects:2,model:3,illustrations:3,cutouts:3,verification:4,repair:4,'repair-complete':4,review:4,video:4,direction:5,render:5,complete:5};
 const actionStep=s.action==='reprompt'?2:s.action==='regenerate'?3:['verify','repair'].includes(s.action)?4:['patch','rerender'].includes(s.action)?5:0;
 const current=actionStep||mapping[s.stage]||0;
 const running=!!s.action||['queued','running','review'].includes(s.status);
 const ready=(s.images||[]).filter(image=>image.variants?.some(v=>v.current)).length;
 const labels=['Timing','Prompts',(s.images?.length?ready+'/'+s.images.length+' Imgs':'Images'),'Review','Kinetic Text'];
 card.querySelectorAll('.pipe-step').forEach(el=>{
  const step=+el.dataset.step;let status='pending';
  if(s.status==='complete')status='done';
  if(step<current)status='done';
  if(step===current)status=running?'active':['failed','cancelled'].includes(s.status)?'failed':s.status==='complete'?'done':'pending';
  el.dataset.status=status;
  el.style.background=status==='done'?'#ffffff0a':status==='active'?'#ffffff16':status==='failed'?'#60402255':'#ffffff06';
  el.style.borderColor=status==='done'?'#ffffff38':status==='active'?'#c5c9d6':status==='failed'?'#dcae70':'#ffffff22';
  el.style.color=status==='done'?'#a6f3c1':status==='active'?'var(--ink)':status==='failed'?'var(--warn)':'var(--muted)';
  const icon=el.querySelector('.step-icon');if(icon)icon.textContent=status==='done'?'✓':status==='active'?'●':status==='failed'?'!':'○';
  const label=el.querySelector('.step-name');if(label)label.textContent=labels[step-1];
 });
 const badge=$('projectStepBadge');if(badge){badge.textContent=s.status==='complete'&&!s.action?'Complete':current?'Step '+current+'/5'+(running?' · active':''):s.status;badge.style.color=s.status==='failed'?'var(--warn)':'var(--lime)'}
}
function refreshProjectPipelineLive(s){
 paintLivePipeline(s);
 const expected=jobId;if(!expected)return;
 const signature=JSON.stringify([expected,s.status,s.stage,s.action,s.video,(s.images||[]).map(i=>i.variants?.filter(v=>v.current).length)]);
 const active=!!s.action||['running','queued','review'].includes(s.status);
 if(livePipelinePending||(signature===livePipelineSignature&&(!active||Date.now()-livePipelineAt<2400)))return;
 livePipelinePending=true;livePipelineSignature=signature;livePipelineAt=Date.now();
 updateProjectPipelineStatus(expected,{live:true}).then(()=>{if(jobId===expected&&state)paintLivePipeline(state)}).finally(()=>{livePipelinePending=false});
}


// Header model pills show the models chosen for the next generation. They ask the server whether each one is on
// this computer (and, for Ollama, loaded in memory) and colour themselves: grey until downloaded, blue once ready.
let readinessTimer=0,readinessKey='',autoTextModel='';
const READINESS_NOTES={off:'not used',missing:'not on this computer yet; it downloads when a generation starts',ready:'downloaded, not loaded',loaded:'loaded in memory now'};
// "Label · model" becomes Label: (model): the label stands outside, only the model's name is in the pill
function setPill(id,text,title){const pill=$(id);if(!pill)return;
 const at=text.indexOf(' · '),label=at<0?'':text.slice(0,at),name=at<0?text:text.slice(at+3);
 if(pill.dataset.text!==text){pill.dataset.text=text;
  const head=document.createElement('b');head.className='model-label';head.textContent=label?label+':':'';
  const body=document.createElement('span');body.className='model-name';body.textContent=name;
  pill.replaceChildren(...(label?[head]:[]),body)}
 pill.dataset.base=title;pill.title=title+(pill.dataset.note?' ('+pill.dataset.note+')':'')}
let readinessAt=0;
function refreshModelReadiness(){
 clearTimeout(readinessTimer);
 readinessTimer=setTimeout(async()=>{
  const query=new URLSearchParams({text:$('aiModel')?.value||'',image:$('imageModel')?.value||'',vision:$('autoVerify')?.checked?($('visionModel')?.value||''):'',video:$('videoGeneration')?.checked?($('videoModel')?.value||''):'',end:endFrameModel(),cache:$('cache')?.value||''});
  // asked again every few seconds even when nothing was changed: models load and unload as the work goes on
  const key=query.toString();if(key===readinessKey&&Date.now()-readinessAt<4000)return;readinessKey=key;readinessAt=Date.now();
  let ready;try{ready=await api('/api/models/ready?'+key)}catch{readinessKey='';return}
  if(readinessKey!==key)return;
  const pills={text:'headerTextModel',image:'headerSelectedImage',vision:'headerVisionModel',video:'headerVideoModel',end:'headerEndModel'};
  // the transcription and word timing models are in memory only while Timing runs
  const timing=typeof state!=='undefined'&&state&&['running','queued'].includes(state.status)&&state.stage==='alignment';
  for(const id of ['headerAsrModel','headerTimingModel']){const pill=$(id);if(pill){pill.dataset.state=timing?'loaded':'ready';pill.dataset.note=READINESS_NOTES[pill.dataset.state]}}
  for(const [kind,id] of Object.entries(pills)){const pill=$(id),info=ready[kind];if(!pill||!info)continue;pill.dataset.state=info.state;pill.dataset.note=READINESS_NOTES[info.state]||'';pill.title=(pill.dataset.base||'')+(pill.dataset.note?' ('+pill.dataset.note+')':'')}
  showMapLoaded();
  const resolved=ready.text?.resolved||'';
  if(resolved!==autoTextModel){autoTextModel=resolved;renderProductionStages(typeof state!=='undefined'?state:null)}
 },300);
}
document.addEventListener('change',event=>{if(['asrModel','alignmentModel','aiModel','imageModel','visionModel','autoVerify','videoModel','videoGeneration','cache'].includes(event.target?.id))renderProductionStages(typeof state!=='undefined'?state:null)});
// Settings also change without events (session restore, profiles): a slow tick catches up; it only asks the server when the choice changed.
setInterval(()=>{if(document.getElementById('headerTextModel')){renderProductionStages(typeof state!=='undefined'?state:null);refreshModelReadiness()}},3000);

function renderProductionStages(s=null){
 // Built off-page and swapped in only when it changed: a running job polls about once a second, and rebuilding
 // every time would throw away the element under the pointer mid-click.
 const shown=$('stages'),host=document.createElement('div');
 renderPipelineHistory(s);
 const saved=s?.production_models;
 const image=saved?.image||$('imageModel').value;
 const prompt=saved?.prompt||$('aiModel').value;
 const asr=saved?.asr||$('asrModel').value;
 const alignment=saved?.alignment||$('alignmentModel').value;
 const vision=saved?saved.vision:($('autoVerify').checked?$('visionModel').value:'');
 const encoder=saved?.encoder||$('encoder').value;
 const imageName=saved?(imageModels.find(m=>m.id===image)?.name||image):($('imageModel').selectedOptions[0]?.textContent||image||'Choose image model');
 const asrName=saved?(audioModels.find(m=>m.id===asr)?.name||asr):($('asrModel').selectedOptions[0]?.textContent||asr);
 const promptName=!prompt||prompt==='auto'?'Auto text model':prompt;
 const reviewName=saved?(vision||'Off'):($('autoVerify').checked?(vision||'Choose vision model'):'Off');
 const castName=saved?promptName:($('castReference')?.checked&&$('visionModel').value?$('visionModel').value+' · '+promptName:promptName);
 const layout=saved?.artwork_mode||$('artworkMode')?.value||'cutout';
 const pictureMode=saved?.stage_pictures||$('stagePictures')?.value||'ai-painted';
 const pictureName={'ai-painted':'AI · '+imageName.replace(/^Used · /,''),'ai-library':'AI · library pictures','keywords':'Keyword matches','off':'Off'}[pictureMode]||pictureMode;
 const summary=s?.pipeline_summary,videoInfo=summary?.video;window.headerSummary=summary||{};
 const videoModel=saved?(saved.video||''):($('videoModel')?.value||'');
 const videoName=saved?(videoModel.split('/').pop()||''):($('videoModel')?.selectedOptions[0]?.textContent||videoModel);
 const videoLabel=!videoModel?'Off · no video model':videoName+(videoInfo&&videoInfo.total?` · ${videoInfo.made}/${videoInfo.total} clips`:'');
 const storyWanted=!!videoModel||!!(saved?(s?.render_settings?.story_prompt):$('storyPrompt')?.value)?.trim?.();
 const storyLabel=!storyWanted?'Off · no story and no AI video':summary?.story?`${promptName} · ${summary.story.segments} segments`+(summary.story.edited?' · edited':''):promptName;
 const sectionsLabel=summary?.sections?`${summary.sections.count} sections · ${summary.sections.shortest}–${summary.sections.longest} s`:'Estimated after Prompts';
 // imageModels is declared in a later script: the first draw at start-up runs before it exists, and touching it
 // then throws and stops the page loading (the project list stays empty)
 let imageSpec=null;try{imageSpec=imageModels.find(m=>m.id===image)}catch{}
 const refsInfo=summary?.references,sceneInfo=summary?.scene,sceneOn=!!window.sceneLyricsEnabled?.();
 const refsSkip=imageSpec&&!imageSpec.references?`Skipped · ${imageSpec.name} takes no reference images`:!storyWanted?'Off · no storyline':'';
 const refsLabel=refsSkip||(!refsInfo?'After the storyline':!refsInfo.listed?'None recurring':`${refsInfo.listed} recurring · ${refsInfo.painted} painted`)+(layout==='matte'&&!refsSkip?' · objects only (greenscreen)':'');
 const sceneDone=!!sceneInfo?.total&&sceneInfo.judged>=sceneInfo.total;
 // Final cut: sections still showing a still (or an older clip) until they are rebuilt with their new clip
 const toRebuild=new Set([...(s?.dirty||[]),...(s?.queued_actions||[]).filter(q=>q.action==='patch').map(q=>q.index)]).size;
 const finalBusy=s?.action==='patch',finalDone=!!videoInfo?.total&&videoInfo.made>=videoInfo.total&&!toRebuild&&!finalBusy;
 const finalLabel=!videoInfo?.made?'After AI video':finalBusy?`Rebuilding · ${toRebuild} section${toRebuild===1?'':'s'} left`:
  toRebuild?`${toRebuild} section${toRebuild===1?'':'s'} to rebuild`:videoInfo.made<videoInfo.total?`${videoInfo.made}/${videoInfo.total} clips in the video`:'Every clip is in the video';
 // Upscale (LTX-2.5): Initial (1280x736) -> Review (the user accepts each clip) -> Upscale (1920x1088)
 const upscaleMode=$('videoUpscale')?.value||'off',upscaled=videoInfo?.upscaled||0,made=videoInfo?.made||0;
 const upscaling=s?.action==='animate'&&/^Upscaling/.test(s?.detail?.message||'');
 const reviewLabel=upscaleMode==='off'?'Off · Upscale is off':upscaleMode==='auto'?'Skipped · upscaled automatically':made?`${Math.max(0,made-upscaled)} clip${made-upscaled===1?'':'s'} to review`:'After the first clips';
 const upscaleLabel=upscaleMode==='off'?'Off · turn on under AI video':upscaling?'Upscaling':`${upscaled}/${videoInfo?.total||0} at 1920x1088`;
 const sceneLabel=!sceneOn?'Off · in-scene lyrics disabled':sceneInfo?.total?`${sceneInfo.judged}/${sceneInfo.total} clips judged`:'After AI video';
 const visionName=saved?(vision||''):($('visionModel')?.value||'');
 const refsChecked=summary?.references,imagesChecked=summary?.images;
 const checkRefsLabel=refsSkip?'Skipped · no references':!visionName?'Off · no vision model':refsChecked?.checked?`${visionName} · ${refsChecked.checked} checked · ${refsChecked.failed} failed`:visionName;
 const checkImagesLabel=reviewName==='Off'?'Off · validation off':imagesChecked?.reviewed?`${reviewName} · ${imagesChecked.reviewed} checked · ${imagesChecked.rejected} rejected`:reviewName;
 const labels={references:refsLabel,'reference-check':checkRefsLabel,'illustration-check':checkImagesLabel,'scene-scan':sceneLabel,final:finalLabel,pictures:pictureName,alignment:[asrName,alignment==='auto'?'Auto timing':alignment].filter(Boolean).join(' · '),song:castName,meanings:promptName,scenes:promptName,fit:promptName+' → '+imageName,model:saved?'Used · '+imageName:imageName,illustrations:saved?'Used · '+imageName:imageName,cutouts:'BiRefNet General',review:reviewName,direction:promptName,render:encoder||'H.264',sections:sectionsLabel,video:videoLabel,story:storyLabel};labels['clip-review']=reviewLabel;labels.upscale=upscaleLabel;
 const audio=saved?.audio||$('audio').files[0]?.name||'No audio selected';
 const profile=localStorage.getItem('lyricStudioProfilesV1Active')||'No saved profile';
 const selectedImage=$('imageModel').selectedOptions[0]?.textContent||'Choose image model';
 $('headerAudio').textContent=audio;$('headerAudio').title=audio;
 $('headerProfile').textContent=profile;$('headerProfile').title=profile+(saved?.profile&&saved.profile!==profile?' · this project used '+saved.profile:'');
 // The pills name what is selected now, which is what the next generation uses; the hover adds what this project used.
 const pickPrompt=$('aiModel')?.value||'auto',pickPromptName=pickPrompt==='auto'?'Auto'+(autoTextModel?' \u2192 '+autoTextModel:''):pickPrompt;
 // The scoring pill names the selected model even while validation is switched off, and says that it is off.
 const visionPicked=$('visionModel')?.value?($('visionModel').selectedOptions[0]?.textContent||$('visionModel').value):'';
 const pickVision=$('autoVerify')?.checked?(visionPicked||'Choose a vision model'):(visionPicked?visionPicked+' \u00b7 validation off':'Off');
 const pickAsr=$('asrModel')?.selectedOptions[0]?.textContent||$('asrModel')?.value||'Choose a model';
 const pickTiming=$('alignmentModel')?.selectedOptions[0]?.textContent||$('alignmentModel')?.value||'Auto';
 const pickVideo=$('videoGeneration')?.checked?($('videoModel')?.selectedOptions[0]?.textContent||'Choose video model'):'Off';
 const usedNote=(used,pick)=>saved&&used&&used!==pick?' \u00b7 this project used '+used:'';
 setPill('headerSelectedImage','Image model \u00b7 '+selectedImage,'Image model: '+selectedImage+usedNote(imageName.replace(/^Used \u00b7 /,''),selectedImage));
 setPill('headerTextModel','Text model \u00b7 '+pickPromptName,'Text model: '+pickPromptName+usedNote(saved?.prompt,pickPrompt));
 setPill('headerAsrModel','Transcription \u00b7 '+pickAsr,'Audio transcription model: '+pickAsr+usedNote(saved?.asr?asrName:'',pickAsr));
 setPill('headerTimingModel','Word timing \u00b7 '+pickTiming,'Word timing model: '+pickTiming+usedNote(saved?.alignment,$('alignmentModel')?.value));
 setPill('headerVisionModel','Image scoring \u00b7 '+pickVision,'Image quality scoring model: '+pickVision+usedNote(saved?(saved.vision||'Off'):'',$('visionModel')?.value||''));
 setPill('headerVideoModel','Video model \u00b7 '+pickVideo,'Video model: '+pickVideo+usedNote(saved?(saved.video_generation&&saved.video?saved.video:'Off'):'',pickVideo));
 const endId=endFrameModel(),endName=(()=>{try{return imageModels.find(m=>m.id===endId)?.name}catch{return ''}})()||endId||'Off';
 const endTitle=!endId?'End frame generator: off, each segment is made from its prompt alone':endId===$('imageModel')?.value?'End frame generator: '+endName:`End frame generator: ${endName} paints where each segment ends`+(($('endFrameModel')?.value||'auto')==='auto'?`; ${selectedImage} cannot edit a picture`:'');
 setPill('headerEndModel','End frames \u00b7 '+endName,endTitle);
 $('headerVideoModel').hidden=$('headerEndModel').hidden=!$('videoGeneration')?.checked;
 syncModelColours();refreshModelReadiness();
 // Older runs and single-image prompt rewrites report all prompt work as 'subjects'.
 const stageName=({subjects:'song',verification:'illustration-check',repair:'illustration-check'})[s?.stage]||s?.stage;
 const current=s?.status==='complete'?stages.length:stages.indexOf(stageName);
 const startSelect=$('startStep'),substep=$('startSubstep');
 // Only a run that is actually going highlights its sub-step; a cancelled or failed run leaves it plain.
 const live=['running','queued'].includes(s?.status)&&!s?.action;
 window.headerProgress={current,hasJob:!!jobId,running:!!s?.action||['running','queued'].includes(s?.status),
  queued:s?.status==='queued',stage:stageName};
 let number=0;const numbered=new Set();let fork=null;const tracks={};
 // AI video appears in the pipeline only while it is switched on in the settings.
 const videoOn=!!($('videoGeneration')?.checked&&$('videoModel')?.value);
 for(const value of ['video','scene-scan']){const o=startSelect?.querySelector(`option[value="${value}"]`);if(o){o.hidden=!videoOn;if(!videoOn&&startSelect.value===value)startSelect.value='beginning'}}
 const overlayOn=kineticSettings().overlay_text!==false;
 for(const [value,on] of [['render',overlayOn],['scene-scan',videoOn&&sceneOn]]){const o=startSelect?.querySelector(`option[value="${value}"]`);if(o){o.hidden=!on;if(!on){if(o.dataset.beforeLyricsOff===undefined)o.dataset.beforeLyricsOff=String(o.disabled);o.disabled=true;if(startSelect.value===value)startSelect.value='beginning'}else if(o.dataset.beforeLyricsOff!==undefined){o.disabled=o.dataset.beforeLyricsOff==='true';delete o.dataset.beforeLyricsOff}}}
 PIPELINE_STEPS.forEach((step,index)=>{
  if(step.value==='render'&&!overlayOn||step.value==='scene-scan'&&!sceneOn||['video','scene-scan','final'].includes(step.value)&&!videoOn){if(!step.own)number++;return;}
  // After Review the graph forks: the kinetic text and the AI video are made independently (timing edits touch
  // only the text), and join in Final cut. Each track is a row of its own inside the fork.
  let place=host;
  if(step.track&&videoOn){
   if(!fork){fork=node('div','stage-fork');const arrow=node('span','stage-arrow','->');arrow.setAttribute('aria-hidden','true');host.append(arrow,fork);
    for(const [key,label] of [['text','Text track'],['video','Video track']]){const row=node('div','stage-track');row.dataset.track=key;row.setAttribute('aria-label',label);tracks[key]=row;fork.append(row)}}
   place=tracks[step.track];
  }
  if(place.childElementCount){const arrow=node('span','stage-arrow','->');arrow.setAttribute('aria-hidden','true');place.append(arrow)}
  if(!step.own)number++;
  const option=startSelect?.querySelector(`option[value="${step.value}"]`);
  // the Restart-at list reads the same numbers as the graph (Prompts names its first sub-step's number)
  if(option&&!step.own&&!numbered.has(step.value)){numbered.add(step.value);option.textContent=`Restart at ${number} · ${step.name}`}
  const pill=node('button','stage');pill.type='button';pill.dataset.step=step.key||step.value;
  pill.append(node('span','stage-name',step.own?step.name:`${number}. ${step.name}`));
  if(step.own)pill.classList.add('status-only');
  const parts=node('span','stage-parts');
  step.stages.filter(name=>!(step.value==='images'&&name==='model')).forEach((name,i)=>{
   if(i){const arrow=node('span','stage-arrow','→');arrow.setAttribute('aria-hidden','true');parts.append(arrow)}
   const part=node('span','stage-part');
   const partName=name==='video'?'Initial':name==='clip-review'?'Review':stageTitle(name);
   part.append(node('span','stage-part-name',partName),node('span','stage-model',labels[name]));
   if(saved&&$('imageModel').value&&$('imageModel').value!==image&&['model','illustrations'].includes(name)){
    part.append(node('span','stage-selected','Selected · '+selectedImage));
   }
   if(name==='cutouts'&&layout!=='cutout'){part.classList.add('skipped');part.querySelector('.stage-model').textContent='Skipped · full-frame artwork'}
   else if(name==='video'){
    if(!videoModel)part.classList.add('skipped');
    else if(s?.action==='animate')part.classList.add('active');
    else if(videoInfo&&videoInfo.total&&videoInfo.made>=videoInfo.total)part.classList.add('done');
   }
   else if(name==='clip-review'){
    if(upscaleMode!=='review')part.classList.add('skipped');
    else if(made&&upscaled>=made)part.classList.add('done');
    else if(made>upscaled)part.classList.add('active');
   }
   else if(name==='upscale'){
    if(upscaleMode==='off'&&!upscaled)part.classList.add('skipped');
    else if(upscaling)part.classList.add('active');
    else if(videoInfo?.total&&upscaled>=videoInfo.total)part.classList.add('done');
   }
   else if(name==='references'){
    if(refsSkip)part.classList.add('skipped');
    else if(stageName==='references'&&live||s?.action_stage==='references')part.classList.add('active');
    else if(refsInfo&&refsInfo.painted>=refsInfo.listed||stages.indexOf(name)<current)part.classList.add('done');
   }
   else if(name==='final'){
    if(finalBusy)part.classList.add('active');
    else if(finalDone)part.classList.add('done');
   }
   else if(name==='scene-scan'){
    if(!sceneOn)part.classList.add('skipped');
    else if(s?.action==='scene-scan')part.classList.add('active');
    else if(sceneDone)part.classList.add('done');
   }
   else if(name==='sections'&&summary?.sections)part.classList.add('done');
   else if(name==='story'){
    if(!storyWanted)part.classList.add('skipped');
    else if((stageName==='story'&&live)||s?.action==='story')part.classList.add('active');
    else if(summary?.story)part.classList.add('done');
   }
   else if(name===stageName&&live)part.classList.add('active');
   else if(stages.indexOf(name)<current)part.classList.add('done');
   // Prompt sub-steps can be restarted from once everything before them is saved.
   if(step.value==='prompts'&&(window.promptSubsteps||[]).includes(name)&&option&&!option.disabled){
    part.classList.add('choosable');part.setAttribute('role','button');
    if(startSelect.value==='prompts'&&(substep.value||'song')===name)part.classList.add('selected',startResumes()?'keeps':'redoes');
    part.title=`Start the next generation at Prompts › ${stageTitle(name)}, reusing the saved prompting work before it.`;
    part.onclick=event=>{
     event.stopPropagation();
     const chosen=startSelect.value==='prompts'&&(substep.value||'song')===name;
     startSelect.value=chosen?'beginning':'prompts';startSelect.dispatchEvent(new Event('change',{bubbles:true}));
     substep.value=chosen||name==='song'?'':name;renderProductionStages(s);
    };
   }else if(step.value==='images'&&['references','illustrations'].includes(name)&&option&&!option.disabled){
    part.classList.add('choosable');part.setAttribute('role','button');
    if(startSelect.value==='images'&&substep.value===name)part.classList.add('selected',startResumes()?'keeps':'redoes');
    part.title=name==='illustrations'?'Regenerate illustrations only; keep all reference pictures and their acceptance.':'Regenerate reference pictures first, then illustrations.';
    part.onclick=event=>{event.stopPropagation();const chosen=startSelect.value==='images'&&substep.value===name;startSelect.value=chosen?'beginning':'images';startSelect.dispatchEvent(new Event('change',{bubbles:true}));substep.value=chosen?'':name;renderProductionStages(s)};
   }else if(name==='sections'){
    part.title=summary?.sections?`Estimated time each section (one illustration and its clip) is on screen: ${summary.sections.seconds.map(x=>x+' s').join(', ')}.`:
     'Once the prompts have grouped the lyrics, the time each section is on screen is estimated here.';
   }else if(name==='story'){
    part.title=videoModel?'The director writes one storyline across every image (characters, place, camera and timed beats), after the prompts and before the images. Edit or rewrite it in the storyline panel.':
     'The storyline guides the AI video clips; with no video model it is not written.';
   }else if(name==='references'){
    part.title=refsSkip?refsSkip.replace('Skipped · ','Reference pictures are skipped: ').replace('Off · ','Reference pictures are off: '):
     'Each character, object or place the storyline shows in two or more segments is painted once on its own, and that picture guides every image that shows it, so it looks the same from scene to scene. The AI video clips get its description.';
   }else if(name==='final'){
    part.title='The finished video, rebuilt section by section with each AI clip (and its in-scene lyrics) in place of the still. It starts by itself when clips are made or in-scene lyrics are applied; only the changed sections are rebuilt.';
   }else if(name==='scene-scan'){
    part.title=sceneOn?'After each clip is animated, the vision model judges it for in-scene lyrics (water, land or sky to set the words in). Suggestions show on the gallery cards.':
     'In-scene lyrics are switched off on the Scenes tab, so clips are not judged for lyric spots.';
   }else if(name==='clip-review'){
    part.title=upscaleMode==='off'?'Upscale is off (AI video settings, under the video model), so clips stay at 1280x736 and are not held for review.':upscaleMode==='auto'?'Upscale is set to Automatically, so clips are not held for review.':
     'Watch each clip on its card. Upscale to 1080p accepts it; Start animation over or Regenerate from segment redoes it first.';
   }else if(name==='upscale'){
    part.title='An accepted clip is sharpened to 1920x1088, frame by frame, with Real-ESRGAN; its motion stays exactly the same. A few seconds per clip; the video is rebuilt with it afterwards.';
   }else if(name==='video'){
    part.title=videoModel?'AI video runs as its own job after the render. Re-running the lyrics, typography or render reuses every finished clip; only new or changed illustrations are animated.':
     'No video model is chosen, so the illustrations stay still.';
   }else{
    part.title=step.value==='prompts'?`${stageTitle(name)} can be chosen once the prompting work before it has been saved by a run.`:
     step.value==='images'?`${step.name} runs as one step: each image is generated, then cut out. Click to start at ${step.name}.`:
     step.value==='render'?`Starting at ${step.name} reuses the saved typography plan and renders again.`:
     `Click to start at ${step.name}.`;
   }
   parts.append(part);
  });
  pill.append(parts);
  const models=[...new Set(step.stages.map(name=>labels[name]))].join(' · ');
  const indices=step.stages.map(name=>stages.indexOf(name));
  if(Math.max(...indices)<current)pill.classList.add('done');
  else if(step.stages.includes(stageName)&&live){pill.classList.add('active');pill.setAttribute('aria-current','step')}
  if(step.value==='scene-scan'){  // runs after the clips, outside the run's own stages
   pill.classList.toggle('done',sceneOn&&sceneDone);pill.classList.toggle('active',s?.action==='scene-scan');
  }
  if(step.value==='final'){pill.classList.toggle('done',finalDone);pill.classList.toggle('active',finalBusy)}
  if(parts.querySelector('.stage-part.active'))pill.classList.add('active');  // a running part lights its parent too
  const available=!step.own&&option&&!option.disabled&&(!step.sub||(window.promptSubsteps||[]).includes(step.sub));
  const chosenSub=$('startSubstep')?.value||'';
  const isSelected=startSelect?.value===step.value&&(step.value!=='prompts'||(step.sub?chosenSub===step.sub||(step.sub==='scenes'&&chosenSub==='fit'):!['story','scenes','fit'].includes(chosenSub)));
  pill.setAttribute('aria-disabled',String(!available));if(!available)pill.classList.add('unavailable');
  if(isSelected)pill.classList.add('selected',startResumes()?'keeps':'redoes');
  pill.setAttribute('aria-pressed',String(!!isSelected));
  pill.title=`${step.name}: ${step.stages.map(stageTitle).join(', ')} · ${models}
`+(step.own?'Runs as its own job, so it is never redone when you restart at an earlier step or re-render.':available?`Click to start the next generation at ${step.name}.`:`${step.name} needs earlier steps finished first.`);
  pill.onclick=()=>{if(!startSelect||!available)return;
   startSelect.value=isSelected?'beginning':step.value;
   if($('startSubstep'))$('startSubstep').value=!isSelected&&step.sub?step.sub:'';
   startSelect.dispatchEvent(new Event('change',{bubbles:true}));renderProductionStages(s)};
  const versioned=node('div','stage-versioned');versioned.append(pill);
  const key=step.key||step.value,history=s?.pipeline_history?.nodes?.[key];
  const versionSelect=node('select','stage-version');
  versionSelect.setAttribute('aria-label',`${step.name} version`);
  if(!history?.current){const empty=new Option(history?.versions?.length?'Needs regeneration':'Not saved','');empty.disabled=true;empty.selected=true;versionSelect.add(empty);pill.classList.remove('done')}
  for(const version of [...(history?.versions||[])].reverse()){
   const option=new Option(`v${version.id}${version.compatible?'':' · different inputs'}`,String(version.id));
   option.disabled=!version.compatible;option.toggleAttribute('selected',version.id===history.current);versionSelect.add(option);
  }
  versionSelect.disabled=pipelineHistoryBusy(s)||!history?.versions?.some(version=>version.compatible);
  versionSelect.title='Choose a saved version. Later nodes select their newest compatible saved versions.';
  versionSelect.onchange=()=>selectPipelineVersion({node:key,version:Number(versionSelect.value)});
  versioned.append(versionSelect);place.append(versioned);
 });
 if(!document.activeElement?.matches?.('select.stage-version')&&host.innerHTML!==shown.innerHTML)shown.replaceChildren(...host.childNodes);
 syncStartAtStage();
}
function pipelineHistoryBusy(s){return !jobId||busy||uploading||!!s?.action||!!s?.queued_actions?.length||!!s?.image_edit_status||['running','queued','review'].includes(s?.status)}
async function selectPipelineVersion(selection){
 if(!jobId||busy||uploading)return;const expected=jobId;busy=true;document.activeElement?.blur?.();
 try{
  await api(`/api/jobs/${expected}/pipeline-version`,selection,300000);
  if(jobId===expected)setJob(expected);
 }catch(error){toast(error.message)}finally{busy=false;if(jobId===expected)poll()}
}
function renderPipelineHistory(s){
 const host=$('pipelineHistory');if(!host)return;
 // Do not replace a focused dropdown while a status poll arrives.
 if(host.contains(document.activeElement))return;
 host.replaceChildren();if(!jobId)return;
 const history=s?.pipeline_history;
 if(!history?.sequences?.length){
  const save=node('button','','Save current pipeline');save.type='button';save.disabled=pipelineHistoryBusy(s);
  save.onclick=()=>selectPipelineVersion({initialize:true});host.append(save);return;
 }
 const label=node('label','','Pipeline '),select=node('select','pipeline-version');
 select.setAttribute('aria-label','Saved pipeline version');
 for(const sequence of [...history.sequences].reverse()){
  const option=new Option(`v${sequence.id} · ${sequence.reason}`,String(sequence.id));
  option.toggleAttribute('selected',sequence.id===history.active);select.add(option);
 }
 select.disabled=pipelineHistoryBusy(s);select.onchange=()=>selectPipelineVersion({sequence:Number(select.value)});
 label.append(select);host.append(label);
}
const PIPELINE_STEPS=[
 {value:'timing',name:'Timing',stages:['alignment']},
 // Prompting runs as three steps, each restartable on its own (a restart at Prompts with that sub-step): the song,
 // the storyline the text model writes in one go, then the image prompts that paint its moments.
 {value:'prompts',key:'prompts',name:'Prompts',stages:['song','meanings']},
 {value:'prompts',key:'story',sub:'story',name:'Storyline',stages:['story']},
 {value:'prompts',key:'image-prompts',sub:'scenes',name:'Image prompts',stages:['scenes','fit','sections']},
 // References: a picture of each character, object or place that recurs across segments, painted before the images.
 // Check 1 looks at every reference picture (failed ones are painted and checked again) before any illustration is
 // painted from it; Check 2 looks at every illustration (rejected ones are replaced and checked again).
 {value:'images',name:'Images',stages:['model','references','reference-check','illustrations','illustration-check','cutouts']},
 {value:'review',name:'Review',stages:['review']},
 {value:'render',name:'Kinetic Text',stages:['direction','pictures','render'],track:'text'},
 // AI video is its own job, queued when the run (rendered with the still images) finishes; it animates every image and
 // rebuilds the video with the clips. Re-running the lyrics, typography or render reuses every finished clip.
 {value:'video',name:'AI video',stages:['video','clip-review','upscale'],track:'video'},
 // In-scene lyric spots: each finished clip judged for water, land or sky to set lyrics in; shown with AI video only.
 {value:'scene-scan',name:'In-scene lyric spots',stages:['scene-scan'],track:'video'},
 // Final cut: the finished video rebuilt with the AI clips and in-scene lyrics, section by section, automatically.
 {value:'final',name:'Final cut',stages:['final'],own:true}];
const stageTitle=name=>({'reference-check':'Check 1 · references','illustration-check':'Check 2 · illustrations'})[name]||name[0].toUpperCase()+name.slice(1);
// True when starting at the chosen step keeps everything already made: the last run stopped inside or before it.
// Otherwise starting there redoes saved work. The button's Resume/Regenerate and the node's outline both follow it.
function startResumes(){
 const select=$('startStep');const step=PIPELINE_STEPS.find(step=>step.value===select?.value);
 // the AI video track resumes while it has work left: clips not made yet, or clips not judged yet
 const summary=window.headerSummary||{};
 if(step?.value==='video')return !!summary.video&&summary.video.made<summary.video.total;
 if(step?.value==='scene-scan')return !!summary.scene&&summary.scene.judged<summary.scene.total;
 const sub=['prompts','images'].includes(step?.value)?$('startSubstep')?.value||'':'';
 const progress=window.headerProgress||{};
 const end=step?(sub?stages.indexOf(sub):Math.max(...step.stages.map(name=>stages.indexOf(name)))):0;
 return !!step&&progress.hasJob&&progress.current>=0&&progress.current<stages.length&&end>=progress.current;
}
// The start button doubles as Cancel while work runs: a click opens a small warning instead of stopping at once.
function confirmCancel(button){
 let box=document.getElementById('cancelConfirm');
 if(box){box.remove();return}
 box=node('div','cancel-confirm');box.id='cancelConfirm';box.setAttribute('role','alertdialog');box.setAttribute('aria-label','Stop the current work');
 box.append(node('strong','','Stop the current work?'),node('p','','The running step and everything queued after it stop. Finished images, clips and parts are kept.'));
 const row=node('div','row');const stop=node('button','danger','Stop');stop.type='button';const keep=node('button','','Keep running');keep.type='button';
 stop.onclick=()=>{box.remove();action('cancel')};keep.onclick=()=>box.remove();row.append(keep,stop);box.append(row);
 button.after(box);keep.focus();
 const away=event=>{if(!box.contains(event.target)&&event.target!==button){box.remove();document.removeEventListener('pointerdown',away,true)}};
 document.addEventListener('pointerdown',away,true);
}
document.addEventListener('click',event=>{
 const button=event.target.closest?.('#startAtStage');
 if(button?.classList.contains('running')){event.preventDefault();event.stopImmediatePropagation();confirmCancel(button)}
},true);
function syncStartAtStage(){
 const button=$('startAtStage'),select=$('startStep');if(!button||!select)return;
 const step=PIPELINE_STEPS.find(step=>step.value===select.value);
 const subStep=step?.value==='prompts'?PIPELINE_STEPS.find(p=>p.value==='prompts'&&p.sub&&p.sub===($('startSubstep')?.value||'')):null;
 const sub=['prompts','images'].includes(step?.value)?$('startSubstep')?.value||'':'';
 const name=subStep?subStep.name:step?step.name+(sub?' › '+stageTitle(sub):''):'';
 const progress=window.headerProgress||{};
 // Starting at the step where the last run stopped (anywhere inside it), or at a step it never reached, picks up its
 // work: resume. The server then keeps what that step already finished (images made before the stop) and makes the rest.
 // "Regenerate instead" beside a Resume: redo the step's finished work too (e.g. every image, not just the missing ones)
 const resumable=startResumes()&&!!progress.hasJob&&!progress.running;
 if(!resumable)window.forceRegenerate=false;
 const resume=resumable&&!window.forceRegenerate;
 window.resumeStart=resume&&!progress.running;
 let label,kind,help;
 if(!progress.hasJob){label='Start new generation';kind='';help='Start a new generation from the beginning.'}
 else if(resume){label='Resume from '+name;kind='resume';help=`Continue from ${name}, where the last run stopped, keeping everything it finished.`}
 else if(!step||step.value==='timing'){label='Clear and Regenerate';kind='regenerate';help=step?'Redo everything from word timing; existing artwork is replaced.':'Start over in a new session with these settings.'}
 else{
  // The last step that can be restarted redoes only itself: nothing earlier is lost, so it reads as safe (green).
  const open=[...select.options].filter(o=>!o.disabled&&o.value!=='beginning').map(o=>o.value);
  const last=open.length&&open[open.length-1]===step.value&&!sub&&!['video','scene-scan'].includes(step.value);  // remaking every clip is never 'safe'
  label='Regenerate from '+name;kind=last?'resume':'regenerate';
  help=last?`Redo ${name} only; every earlier step is reused.`:`Redo ${name} and every step after it; earlier steps are reused.`}
 if(progress.running){
  // while work runs this button is the Cancel (red, with the running spinner); a click asks first (confirmCancel)
  const stage=stages.includes(progress.stage)?stageTitle(progress.stage):'';
  label='Cancel';kind='running';help=`${progress.queued?'Queued':'Running'}${stage?' ('+stage+')':''}. Click to stop it: you are asked first, and finished work is kept.`;
 }
 const spinner=node('span','busy-spinner');spinner.setAttribute('aria-hidden','true');
 button.replaceChildren(...(kind==='running'?[spinner,label]:[label+' ↗']));button.title=help;
 button.setAttribute('aria-busy',String(kind==='running'));
 for(const name of ['resume','regenerate','running'])button.classList.toggle(name,kind===name);
 button.disabled=kind!=='running'&&$('generate').disabled;
 let other=$('startInstead');
 if(!other){other=node('button','link start-instead');other.type='button';other.id='startInstead';button.after(other);
  other.onclick=()=>{window.forceRegenerate=!window.forceRegenerate;syncStartAtStage()}}
 other.hidden=!resumable;
 other.textContent=window.forceRegenerate?'Resume instead':'Regenerate instead';
 other.title=window.forceRegenerate?`Keep what ${name} already finished and make only the rest.`:
  `Redo ${name} from scratch, including what it already finished (finished work is replaced), and every step after it.`;
}
// a different step starts as a Resume again
document.addEventListener('change',event=>{if(['startStep','startSubstep'].includes(event.target?.id)){window.forceRegenerate=false;syncStartAtStage()}});
function renderProductionHeader(s){
 renderReplacementQueue(s);
 const jobActive=!!s?.action||['running','queued','review'].includes(s?.status);
 const pending=downloadSnapshot.filter(task=>['queued','downloading'].includes(task.status));
 // Only a download actually in flight takes over the header; the model check that queues on every page load does not.
 const downloading=!jobActive&&pending.some(task=>task.status==='downloading');
 let percent=s?.percent||0;
 let status=s?.status||'Ready';
 let message=s?.message||'Ready to generate.';
 // A finished run can still have work going on after it (AI video, Final cut, a re-render, replacements): the
 // status then names that work and the bar shows its own progress, not the run's 100%.
 const ACTION_STATUS={animate:'AI video',patch:'Final cut',rerender:'Re-rendering','clip-effects':'Clip effects','scene-scan':'Lyric spots',
  regenerate:'Replacing images',reprompt:'Rewriting prompts',verify:'Verifying',repair:'Repairing',story:'Storyline'};
 if(s?.action){status=ACTION_STATUS[s.action]||s.action;percent=s.action_percent||0}
 else if(['complete','review'].includes(s?.status)&&(s?.queued_actions||[]).length){status='Queued';percent=0}
 if(downloading){
  const current=pending.find(task=>task.status==='downloading');
  status=current?'Downloading':'Queued';
  message=current?'Downloading '+current.model+(pending.length>1?' · '+(pending.length-1)+' more queued':''):'Waiting to download models.';
  percent=downloadSnapshot.reduce((sum,task)=>sum+(task.status==='complete'?100:Number(task.percent)||0),0)/downloadSnapshot.length;
 }
 percent=Math.max(0,Math.min(100,percent));
 $('status').textContent=status;
 $('message').textContent=message;
 $('percent').textContent=Math.floor(percent);
 $('progressBar').setAttribute('aria-valuenow',percent);
 $('progressBar').setAttribute('aria-label',downloading?'Model download progress':'Estimated overall production progress');
}


function renderReplacementQueue(s){
 let host=$('replacementQueue');
 if(!host){host=node('div','replacement-queue');host.id='replacementQueue';host.setAttribute('aria-label','Work queue');($('queueSlot')||$('actionProgress')).append(host);}
 // Each queue is its own group (images, animation, song-wide tasks), appended in that order: one image can be in
 // more than one (a replacement queued while its clip is being animated), and each shows where it is.
 const images=new Map(),clips=new Map(),songWide=[];
 const queued=(s?.queued_actions||[]).filter(q=>['regenerate','reprompt'].includes(q.action||'regenerate'));
 // Pills in the order the worker reaches them: the image being painted, then the queue in order, then
 // replacements waiting for review.
 const waiting=new Set(s?.replacement_review||[]);
 for(const index of s?.active_images||[])images.set(index,{label:'Generating',kind:'active'});
 if(['verify','repair'].includes(s?.action)&&['subjects','song','meanings','scenes','fit','model','illustrations','cutouts','repair'].includes(s?.action_stage)){
  for(const index of waiting)images.set(index,{label:['subjects','song','meanings','scenes','fit'].includes(s.action_stage)?'Revising prompt':'Repair in progress',kind:'active'});
 }
 for(const q of queued)if(!images.has(q.index))images.set(q.index,{label:q.action==='reprompt'?'Prompt queued':'Queued',kind:'queued'});
 const review=new Map();  // new pictures waiting for you to keep or not: not queued work, a group of their own
 for(const index of waiting){
  if(images.has(index))continue;
  const latest=s?.images?.find(i=>i.index===index)?.variants?.filter(v=>v.path.startsWith('candidates/')).at(-1);
  const ready=latest?.review&&!latest.review.rejected&&!latest.review.validation_pending;
  review.set(index,{label:ready?'Choose replacement':'Review replacement',kind:'review'});
 }
 const batch=[...(s?.animating||[])];
 const current=s?.action==='animate'&&s?.detail?.stage==='video'&&Number.isInteger(s.detail.image)?s.detail.image-1:null;
 const at=current==null?-1:batch.indexOf(current);
 const ahead=at<0?batch:batch.slice(at);  // the worker goes through the batch in order: what precedes the current clip is done
 for(const index of ahead){
  const first=(s.animating_segments||{})[String(index)],redo=(s.redo_pending||{})[String(index)];
  // a redo asked for while this batch runs waits its turn inside it
  clips.set(index,redo!=null?{label:'Redo '+(redo?'from segment '+(redo+1):'from the start')+' queued',kind:'queued'}
                             :index===current||current==null?{label:/^Upscaling/.test(s.detail?.message||'')||(s.animating_upscale||[]).includes(index)&&!(s.detail?.message||'').startsWith('Animating')?'Upscaling':'Animating'+(first?' from segment '+(first+1):''),kind:'active'}
                             :{label:'Next in this animation batch',kind:'queued'});
 }
 for(const index of s?.effecting||[])clips.set(index,{label:'Applying clip effects',kind:'active'});
 for(const q of (s?.queued_actions||[]).filter(q=>q.action==='animate'))
  for(const index of q.indices||[q.index]){
   const first=(q.segments||{})[String(index)];
   if(clips.get(index)?.kind==='active'){clips.get(index).label+=' · again after';continue}
   clips.set(index,{label:(q.upscale||[]).includes(index)?'Upscale queued':'Animation queued'+(first?' from segment '+(first+1):''),kind:'queued'});
  }
 for(const q of (s?.queued_actions||[]).filter(q=>q.action==='clip-effects'))
  for(const index of q.indices||[q.index])if(!clips.has(index))clips.set(index,{label:'Clip effects queued',kind:'queued'});
 // Song-wide tasks, and per-image checks and rebuilds, have pills of their own.
 const SONG_TASKS={story:'Storyline queued','scene-scan':'In-scene lyric spots queued',patch:'Rebuild queued',rerender:'Re-render queued',verify:'Verification queued',repair:'Repair queued'};
 const perImage=new Map(),toRender=new Map();  // checks (verify, repair) and sections waiting to be rendered in
 for(const q of s?.queued_actions||[]){
  const label=SONG_TASKS[q.action];if(!label)continue;
  if(q.action==='patch'&&Number.isInteger(q.index)){if(!toRender.has(q.index))toRender.set(q.index,{label,kind:'queued'});continue}
  if(['verify','repair'].includes(q.action)&&Number.isInteger(q.index)){if(!perImage.has(q.index))perImage.set(q.index,{label,kind:'queued'});continue}
  if(!songWide.some(t=>t.label===label))songWide.push({label,kind:'queued',action:q.action});
 }
 // reference sheets being painted again, named; the images that show them follow in the Image queue
 const references=new Map();
 if(s?.action==='reference')for(const name of s.repainting||[])references.set(name,{label:'Repainting',kind:'active'});
 for(const q of (s?.queued_actions||[]).filter(q=>q.action==='reference')){const name=q.name||q.entity;if(!references.has(name))references.set(name,{label:'Repaint queued',kind:'queued',entity:q.entity})}
 const groups=[
  ['Reference queue',references,'references'],
  ['Image queue',images,'images'],
  ['Animation queue',clips,'animation'],
  ['To render',toRender,'render'],
  ['Checks',perImage,'checks'],
  ['To review',review,'review'],
 ].filter(([,entries])=>entries.size);
 // Left to right in the order the work will run (the server's plan: the running job first, then work for the same
 // model, then the rest), so the next one up is always at the left.
 const GROUP_OF={reference:'references',regenerate:'images',reprompt:'images',animate:'animation','clip-effects':'animation',verify:'checks',repair:'checks',patch:'render',
  story:'song','scene-scan':'song',rerender:'song'};
 const order=[...new Set((s?.queue_plan||[s?.action].filter(Boolean)).map(kind=>GROUP_OF[kind]).filter(Boolean))];
 const rank=kind=>{if(kind==='review')return 999;const at=order.indexOf(kind);return at<0?order.length+['references','images','animation','render','checks','song'].indexOf(kind):at};
 groups.sort((a,b)=>rank(a[2])-rank(b[2]));
 host.replaceChildren();host.hidden=!groups.length&&!songWide.length;if(host.hidden)return;
 const scroller=node('div','replacement-queue-items');
 for(const [title,entries,kind] of groups){
  const group=node('div','replacement-queue-group');group.dataset.queue=kind;group.append(node('strong','replacement-queue-title',title));
  for(const [index,entry] of entries){
   if(kind==='references'){  // a sheet, by name
    const name=String(index),pill=node('span','replacement-queue-pill '+entry.kind,name.charAt(0).toUpperCase()+name.slice(1));
    pill.title=pill.textContent+' · '+entry.label;
    if(entry.kind==='queued'&&entry.entity)pill.append(removeButton({group:'references',entity:entry.entity}));
    group.append(pill);continue;
   }
   // just the illustration: the group says what kind of work it is, the hover says where it is in it
   const pill=node('button','replacement-queue-pill '+entry.kind,'Illustration '+(index+1));
   const own=s?.eta?.items?.[kind+':'+index];
   pill.title='Illustration '+(index+1)+' · '+entry.label+(Number.isFinite(own)?' · '+leftText(own).replace(/ left$/,''):'');pill.type='button';
   if(entry.kind==='queued')pill.append(removeButton({group:kind,index}));pill.onclick=()=>document.querySelector('[data-image-index="'+index+'"]')?.scrollIntoView({behavior:'smooth',block:'center'});
   group.append(pill);
  }
  scroller.append(group);
 }
 if(songWide.length){
  const group=node('div','replacement-queue-group');group.dataset.queue='song';group.append(node('strong','replacement-queue-title','Song'));
  for(const task of songWide){const pill=node('span','replacement-queue-pill '+task.kind,task.label);pill.append(removeButton({group:'song',action:task.action}));group.append(pill)}
  // its place in the order too: before any group that runs after it
  const after=[...scroller.children].find(g=>rank(g.dataset.queue)>rank('song'));
  after?scroller.insertBefore(group,after):scroller.append(group);
 }
 // a queue kept after Cancel waits: Run queue starts it again
 if(!s?.action&&!['running','queued'].includes(s?.status)&&(s?.queued_actions||[]).length){
  const run=node('button','primary queue-run','Run queue');run.type='button';
  run.onclick=async()=>{try{const r=await api(`/api/jobs/${jobId}/queue-run`,{});if(r.error)throw Error(r.error);toast(r.message)}catch(e){toast(e.message||String(e))}};
  host.append(run);
 }
 host.append(scroller);
}
// The small x on a queued pill: takes just that item out of its queue.
function removeButton(item){
 const x=node('span','queue-remove','×');x.setAttribute('role','button');x.tabIndex=0;x.title='Remove from the queue';
 const go=async event=>{event.stopPropagation();event.preventDefault();
  try{const r=await api(`/api/jobs/${jobId}/queue-remove`,item);if(r.error)throw Error(r.error);toast(r.message)}
  catch(e){toast(/not found|unknown/i.test(String(e.message||e))?'Restart the studio to remove single items from the queue.':(e.message||String(e)))}};
 x.onclick=go;x.onkeydown=event=>{if(event.key==='Enter'||event.key===' ')go(event)};
 return x;
}

function appendStableArtwork(stage,active,item,previous){
 // An animated illustration (the video step's clip, or an uploaded clip) shows its still; hovering the card plays
 // the whole clip silently on a loop from the start, and leaving it returns to the still.
 const clip=active.animation||active.video;
 if(clip){
  // The gallery redraws often and reuses the playing element, but each redraw makes a new stage, so the hover
  // handlers and the badge are attached to every stage, whether the video is new or reused.
  const hover=video=>{
   stage.onmouseenter=()=>{video.currentTime=0;video.play().catch(()=>{});};
   stage.onmouseleave=()=>{video.pause();video.currentTime=0;video.load();};
  };
  const addBadge=video=>{
   const badge=document.createElement('span');badge.className='video-badge';badge.title='Video clip · hover to play';
   badge.innerHTML='<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d="M3 1.8v8.4L10 6z" fill="currentColor"/></svg><span>Video</span>';
   // A clip still being made plays the parts made so far, and says so.
   const progress=active.animation_parts?(' · '+active.animation_parts+(active.animation_total?' of '+active.animation_total:'')+' parts'):'';
   if(progress)badge.title='Still animating · hover to play the parts made so far';
   const label=()=>{badge.lastChild.textContent='Video'+(Number.isFinite(video.duration)?' · '+video.duration.toFixed(1).replace(/\.0$/,'')+'s':'')+progress;};
   label();video.addEventListener('loadedmetadata',label);
   stage.append(badge);
  };
  if(previous&&previous.tagName==='VIDEO'&&previous.getAttribute('src')===clip){stage.append(previous);hover(previous);addBadge(previous);return;}
  const video=document.createElement('video');
  video.muted=true;video.loop=true;video.playsInline=true;video.preload='auto';
  video.poster=active.url;video.title=item.subject+' · hover to play';video.setAttribute('aria-label',item.subject);
  video.onclick=()=>inspect(active.url,item.index,clip);
  video.onerror=()=>{const img=document.createElement('img');img.alt=item.subject;img.src=active.url;img.onclick=()=>inspect(active.url,item.index);video.replaceWith(img);};
  video.src=clip;stage.append(video);hover(video);addBadge(video);
  return;
 }
 if(previous&&previous.tagName==='IMG'&&previous.getAttribute('src')===active.url){previous.onclick=()=>inspect(active.url,item.index);stage.append(previous);return;}
 const img=document.createElement('img');img.alt=item.subject;img.onclick=()=>inspect(active.url,item.index);
 if(previous){
  stage.append(previous);
  img.onload=()=>{if(stage.isConnected)previous.replaceWith(img);};
  img.onerror=()=>{const note=node('span','image-progress-label','Preview unavailable · keeping previous image');stage.append(note);};
 }else stage.append(img);
 img.src=active.url;
}


// The illustration's storyboard: cast, shot plan and one prompt per segment (0-5 s, 5-10 s, ...). Written by the
// director, edited here; every segment still to be made follows it. Save & regenerate redoes the clip from a segment.
function openStoryboard(item){}

// Redo an illustration's animation without touching its image: all of it, or from one segment on (the segments
// before it are kept and the rest are made again with a new seed). Returns the controls for the card.
function animationControls(item,active,run){return document.createElement('div');}

const optimisticRegenerations=new Map();
function showOptimisticQueue(snapshot){
 if(!snapshot)return snapshot;
 const queued=(snapshot.queued_actions||[]).filter(q=>!q.optimistic);
 for(const [key,item] of optimisticRegenerations){
  if(item.job!==jobId)continue;
  const confirmed=queued.some(q=>q.action===item.action&&(q.index===item.index||(Array.isArray(q.indices)&&q.indices.includes(item.index))));
  const active=(snapshot.active_images||[]).includes(item.index);
  const ready=(snapshot.replacement_review||[]).includes(item.index);
  if(item.accepted&&(confirmed||active||ready)){optimisticRegenerations.delete(key);continue;}
  if(!confirmed)queued.push({...item,optimistic:true});
 }
 return {...snapshot,queued_actions:queued};
}
function paintOptimisticQueue(){
 if(!state)return;state=showOptimisticQueue(state);gallerySignature='';renderProductionHeader(state);renderGallery(state);
}

const automaticReplacementPreview=new Map();


function syncLetteringChecks(){
 const hidden=document.getElementById('letteringStyles');if(!hidden)return;
 let chosen;try{chosen=JSON.parse(hidden.value||'[]')}catch{chosen=[]}
 if(!Array.isArray(chosen)||!chosen.length)chosen=['swiss','poster','outline','cutout','neon','extrude','split'];
 document.querySelectorAll('.lettering-style').forEach(box=>box.checked=chosen.includes(box.value));
}
window.syncLetteringChecks=syncLetteringChecks;
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('.lettering-style').forEach(box=>box.onchange=()=>{
  const chosen=[...document.querySelectorAll('.lettering-style')].filter(b=>b.checked).map(b=>b.value);
  if(!chosen.length){box.checked=true;return}
  document.getElementById('letteringStyles').value=JSON.stringify(chosen);
 });
 syncLetteringChecks();
});

const KINETIC_DEFAULTS={camera:'pan',pan_speed:.05,backdrop_rate:.6,backdrops:['outline','filled','vertical','echo','giant'],traces:true,geometry:.8,frames:.1,glows:['drums','other','bass'],glow_words:.15,glow_strength:.55,glitch:true,text_pulse:0,word_shapes:0,drum_reactivity:.8,background_shake:.8,shake_all:false,beat_dim:0,chorus_fx:.75,fade:true,beat_effect:'lights',beat_scope:'chorus',beat_confetti:true,beat_intensity:.75,confetti_intensity:.85,beat_blur:0,match_art_colors:false,overlay_text:true};
function kineticSettings(){
 const hidden=document.getElementById('kinetic');let value={};
 try{value=JSON.parse(hidden?.value||'{}')||{}}catch{value={}}
 delete value.thread_shapes;
 if(value.beat_effect==null&&('chorus_fx' in value||'beat_dim' in value||'shake_all' in value)){
  // Saved before the beat options: chorus lights and confetti, a dim slider, "shake all song".
  const fx=+(value.chorus_fx??.75),dim=+(value.beat_dim||0);
  value.beat_effect=fx>0?'lights':dim>0?'dim':'none';
  value.beat_intensity=fx>0?fx:dim>0?dim:.75;value.beat_confetti=fx>0;value.beat_scope=value.shake_all?'song':'chorus';
 }
 return {...KINETIC_DEFAULTS,...value};
}
function syncKineticControls(){
 const settings=kineticSettings();
 document.querySelectorAll('[data-kinetic]').forEach(input=>{input.value=settings[input.dataset.kinetic];showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>box.checked=!!settings[box.dataset.kineticFlag]);
 document.querySelectorAll('[data-kinetic-list]').forEach(box=>{const list=settings[box.dataset.kineticList];box.checked=list==null||list.includes(box.value)});
 document.querySelectorAll('[data-kinetic-choice]').forEach(select=>select.value=settings[select.dataset.kineticChoice]);
 document.querySelectorAll('[data-kinetic-radio]').forEach(radio=>radio.checked=String(settings[radio.dataset.kineticRadio])===radio.value);
 syncBeatControls(settings);
 window.syncSceneControls?.();
 syncCameraMode();
}
window.sceneLyricsEnabled=()=>!!kineticSettings().scene_text;
function syncLyricModes(settings){}
function syncBeatControls(settings){
 syncLyricModes(settings);
 const label=document.getElementById('beatIntensityLabel'),slider=document.querySelector('[data-kinetic="beat_intensity"]');
 if(label)label.textContent=settings.beat_effect==='dim'?'Dim intensity':settings.beat_effect==='lights'?'Lights intensity':'Intensity (no effect chosen)';
 if(slider)slider.disabled=settings.beat_effect==='none';
 const confetti=document.querySelector('.confetti-intensity');if(confetti)confetti.hidden=settings.beat_confetti===false;
}
function syncCameraMode(){
 const flow=document.getElementById('readingFlow')?.value;
 const camera=document.querySelector('[data-kinetic-choice="camera"]')?.value;
 const panning=flow==='realtime'&&camera==='pan';
 const stage=document.querySelector('.stage-controls');if(stage)stage.hidden=!['stage','mixed'].includes(flow);
 const scenes=document.querySelector('.scene-controls');if(scenes)scenes.hidden=flow!=='mixed';
 const kinetic=document.querySelector('.kinetic-controls');if(kinetic)kinetic.hidden=!['realtime','mixed'].includes(flow);
 const help=document.getElementById('readingFlowHelp');
 if(help)help.textContent={realtime:'Real-time mixes typewriter, heavy and huge hero words, follows the newest word with the camera and reacts to the melody.',
  preview:'Each line appears in full before it is sung, then words animate on their timing.',
  stage:'Lines sung together form a rectangular block of justified words in a 3D space; the camera glides from block to block.',
  mixed:'Each verse, chorus and bridge gets its own scene effect, chosen by the AI from the ones ticked below; the video moves between them.',
  cinema:'Two or three words at a time, centred over the artwork: hairline words settle in from oversized, heavy words slide in blurred, some flip in mirrored or stand on end. Works best with full-screen artwork.'}[flow]||'';
 for(const id of ['exitEffect','browseExit']){const el=document.getElementById(id);if(el)el.disabled=panning;}
 const hint=document.getElementById('exitHint');if(hint)hint.hidden=!panning;
 // Every tab says which flows use it, so a setting that does nothing for the chosen flow says so where it sits.
 const uses={
  realtime:{flow:'This flow uses kinetic effects, entrance effects and letter effects. Exit effects play only with the still camera; the panning camera drifts finished lines away.',
            words:'Entrance effects play on every line in the Real-time flow (exits only with the still camera). Letter effects apply.',
            kinetic:'Kinetic effects shape the Real-time flow, which is selected on the Scenes tab.',scenes:'Scene effects are used by the Scene mix flow; Real-time keeps one panning or still camera for the whole song.'},
  preview:{flow:'This flow uses entrance and exit effects and letter effects. Kinetic effects are not used.',
           words:'Entrance and exit effects play on every line in the Preview flow. Letter effects apply.',
           kinetic:'Not used by the Preview flow. Choose Real-time or Scene mix on the Scenes tab to use kinetic effects.',scenes:'Scene effects are used by the Scene mix flow only.'},
  stage:{flow:'This flow uses selected entrance particles, small animated pictures and built-in camera motion. Global exit effects are not used.',
         words:'Selected entrances can decorate the top row of 3D blocks. Global exit effects are not used; earlier blocks dim in the world.',
         kinetic:'Not used by the 3D stage flow. Choose Real-time or Scene mix on the Scenes tab to use kinetic effects.',scenes:'Scene effects are used by the Scene mix flow only; the 3D stage flow films the whole song on its stage.'},
  mixed:{flow:'Each section\u2019s scene decides: panning canvas uses entrances; framed lines use entrances and exits; Spotlight uses its own phrase motion; 3D stage and poster scenes bring their own motion.',
         words:'In Scene mix, panning scenes use entrances; still scenes use entrances and exits. 3D scenes use selected entrances on their top rows. Spotlight and poster scenes use built-in motion.',
         kinetic:'In Scene mix, kinetic effects shape the sections filmed as a panning canvas or framed lines.',scenes:''},
  cinema:{flow:'This flow uses built-in settle, slide, zoom and flip entrances, and blur, flip or slide exits.',
          words:'Spotlight uses its own phrase motion. Global entrance and exit selections are not used.',
          kinetic:'Not used by the Spotlight flow. Choose Real-time or Scene mix on the Scenes tab to use kinetic effects.',scenes:'Scene effects are used by the Scene mix flow only.'}}[flow]||{};
 for(const [id,key] of [['flowUses','flow'],['wordUses','words'],['kineticUses','kinetic'],['scenesUnused','scenes']]){const el=document.getElementById(id);if(el)el.textContent=uses[key]||'';}
 const pan=document.querySelector('[data-kinetic="pan_speed"]');if(pan)pan.disabled=flow==='realtime'&&camera==='still';
}
function showKineticValue(input){
 const out=document.querySelector(`[data-kinetic-out="${input.dataset.kinetic}"]`);
 if(out)out.value=input.dataset.unit==='%'?Math.round(+input.value*100)+'%':(+input.value).toFixed(3);
}
function storeKineticControls(){
 const settings={scene_settings:kineticSettings().scene_settings||{}};
 document.querySelectorAll('[data-kinetic]').forEach(input=>{settings[input.dataset.kinetic]=+input.value;showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>settings[box.dataset.kineticFlag]=box.checked);
 document.querySelectorAll('[data-kinetic-choice]').forEach(select=>settings[select.dataset.kineticChoice]=select.value);
 document.querySelectorAll('[data-kinetic-radio]:checked').forEach(radio=>settings[radio.dataset.kineticRadio]=radio.value==='true'?true:radio.value==='false'?false:radio.value);
 syncBeatControls(settings);
 for(const key of ['backdrops','glows'])settings[key]=[...document.querySelectorAll(`[data-kinetic-list="${key}"]`)].filter(b=>b.checked).map(b=>b.value);
 const scenes=[...document.querySelectorAll('[data-kinetic-list="scenes"]')];
 if(scenes.length)settings.scenes=scenes.filter(b=>b.checked).map(b=>b.value);
 const hidden=document.getElementById('kinetic');if(hidden)hidden.value=JSON.stringify(settings);
 window.syncSceneControls?.();
 syncCameraMode();
 renderProductionStages(typeof state==='undefined'?null:state);
}
window.syncKineticControls=syncKineticControls;
function sceneSampleQuery(id){
 const value=key=>document.getElementById(key)?.value;
 const settings=kineticSettings(),overrides={...(settings.scene_settings?.[id]||{})};
 for(const key of ['pan_speed','backdrop_rate','geometry']){
  if(document.querySelector(`[data-scene-id="${id}"][data-scene-setting="${key}"]`)&&overrides[key]===undefined)overrides[key]=settings[key];
 }
 const query={scene:id,v:'scene-controls-3',settings:JSON.stringify(overrides)};
 for(const [key,field] of [['font_family','fontFamily'],['font_style','fontStyle'],['font_scale','fontScale']])if(value(field))query[key]=value(field);
 return '/api/scene-preview?'+new URLSearchParams(query);
}
function refreshSceneSamples(){document.querySelectorAll('.scene-thumbnail').forEach(img=>{const src=sceneSampleQuery(img.dataset.scene);if(img.getAttribute('src')!==src)img.src=src})}
window.refreshSceneSamples=refreshSceneSamples;

document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-kinetic],[data-kinetic-flag],[data-kinetic-list],[data-kinetic-choice],[data-kinetic-radio]').forEach(input=>input.addEventListener('input',storeKineticControls));
 document.getElementById('readingFlow')?.addEventListener('change',syncCameraMode);
 for(const id of ['fontFamily','fontStyle','fontScale'])document.getElementById(id)?.addEventListener('change',refreshSceneSamples);
 syncKineticControls();storeKineticControls();
});

// Mark each gallery picture as opaque or transparent once it loads, from a few corner pixels, so opaque artwork
// fills its card and only cutouts get a checkerboard.
function classifyGalleryImage(img){
 if(!(img instanceof HTMLImageElement)||!img.complete||!img.naturalWidth||!img.closest('#gallery .image-stage'))return;
 const stage=img.closest('.image-stage');
 try{
  const canvas=document.createElement('canvas');canvas.width=canvas.height=8;
  const context=canvas.getContext('2d',{willReadFrequently:true});context.drawImage(img,0,0,8,8);
  const pixels=context.getImageData(0,0,8,8).data;
  const corners=[0,7,56,63].map(i=>pixels[i*4+3]);
  const transparent=corners.some(alpha=>alpha<250);
  stage.classList.toggle('transparent',transparent);stage.classList.toggle('opaque',!transparent);
 }catch(error){stage.classList.add('opaque')}
}
document.addEventListener('load',event=>classifyGalleryImage(event.target),true);
// This script loads in <head>, before the gallery exists and before studio.html defines $.
document.addEventListener('DOMContentLoaded',()=>new MutationObserver(()=>document.querySelectorAll('#gallery .image-stage img').forEach(classifyGalleryImage))
 .observe(document.getElementById('gallery'),{childList:true,subtree:true}));

// Scene lyrics: huge 3D letters floating on the clip's water or fixed in its sky, baked into the clip (removable).


// the Upscale setting changes the cards' buttons and the graph's AI video stages straight away
document.addEventListener('change',event=>{if(event.target?.id!=='videoUpscale')return;try{gallerySignature='';if(state){renderGallery(state);renderProductionStages(state)}}catch{}});
