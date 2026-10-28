let gpuModelCatalog=null;
const QWEN_IMAGE_DEFAULT='Qwen/Qwen-Image-2512';
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
 startGpuMonitor();
 $('cache').addEventListener('change',scheduleModelDownloads);
 $('aiModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads()});
 $('visionModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads()});
 $('imageModel').addEventListener('change',()=>{$('gpuPreset').value='';scheduleModelDownloads()});
}


let gpuMonitorStarted=false,downloadTimer=null,downloadSelectionKey='',downloadIds=[],downloadRequest=null,downloadPoll=null,downloadSnapshot=[];
function gib(bytes){return (bytes/2**30).toFixed(1)+' GiB'}
function node(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el}
async function refreshGpuUsage(){
 if(document.hidden)return;
 try{
  const data=await api('/api/gpu');const host=$('gpuMemoryCards');host.replaceChildren();
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
 }catch(e){$('gpuMemoryCards').replaceChildren(node('div','help','GPU monitor unavailable: '+e.message))}
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
 const mapping={alignment:1,subjects:2,model:3,illustrations:3,cutouts:3,verification:4,repair:4,'repair-complete':4,review:4,dimensions:5,direction:6,render:6,complete:6};
 const actionStep=s.action==='reprompt'?2:s.action==='regenerate'?3:['verify','repair'].includes(s.action)?4:['patch','rerender'].includes(s.action)?(s.action_stage==='dimensions'?5:6):0;
 const current=actionStep||mapping[s.stage]||0;
 const running=!!s.action||['queued','running','review'].includes(s.status);
 const ready=(s.images||[]).filter(image=>image.variants?.some(v=>v.current)).length;
 const labels=['Timing','Prompts',(s.images?.length?ready+'/'+s.images.length+' Imgs':'Images'),'Review','Dimensions','Video'];
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
 const badge=$('projectStepBadge');if(badge){badge.textContent=s.status==='complete'&&!s.action?'Complete':current?'Step '+current+'/6'+(running?' · active':''):s.status;badge.style.color=s.status==='failed'?'var(--warn)':'var(--lime)'}
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


function renderProductionStages(s=null){
 const host=$('stages');host.replaceChildren();
 const current=s?.status==='complete'?stages.length:stages.indexOf(s?.stage);
 stages.forEach((name,index)=>{
  if(index){const arrow=node('span','stage-arrow','->');arrow.setAttribute('aria-hidden','true');host.append(arrow)}
  const pill=node('span','stage',name[0].toUpperCase()+name.slice(1));
  pill.setAttribute('role','listitem');
  if(index<current)pill.classList.add('done');
  else if(name===s?.stage){pill.classList.add('active');pill.setAttribute('aria-current','step')}
  host.append(pill);
 });
}
function renderProductionHeader(s){
 renderReplacementQueue(s);
 const jobActive=!!s?.action||['running','queued','review'].includes(s?.status);
 const pending=downloadSnapshot.filter(task=>['queued','downloading'].includes(task.status));
 const downloading=!jobActive&&pending.length>0;
 let percent=s?.percent||0;
 let status=s?.status||'Ready';
 let message=s?.message||'Ready to generate.';
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
 $('bar').style.width=percent+'%';
 $('progressBar').setAttribute('aria-valuenow',percent);
 $('progressBar').setAttribute('aria-label',downloading?'Model download progress':'Estimated overall production progress');
}


function renderReplacementQueue(s){
 let host=$('replacementQueue');
 if(!host){host=node('div','replacement-queue');host.id='replacementQueue';host.setAttribute('aria-label','Image replacement queue');$('actionProgress').after(host);}
 const queued=(s?.queued_actions||[]).filter(q=>['regenerate','reprompt'].includes(q.action||'regenerate'));
 const active=new Set(s?.active_images||[]);
 const waiting=new Set(s?.replacement_review||[]);
 const entries=new Map();
 for(const index of waiting){
  const latest=s?.images?.find(i=>i.index===index)?.variants?.filter(v=>v.path.startsWith('candidates/')).at(-1);
  const ready=latest?.review&&!latest.review.rejected&&!latest.review.validation_pending;
  entries.set(index,{label:ready?'Choose replacement':'Review replacement',kind:'review'});
 }
 for(const q of queued)entries.set(q.index,{label:q.action==='reprompt'?'Prompt queued':'Queued',kind:'queued'});
 if(['verify','repair'].includes(s?.action)&&['subjects','model','illustrations','cutouts','repair'].includes(s?.action_stage)){
  for(const index of waiting)entries.set(index,{label:s.action_stage==='subjects'?'Revising prompt':'Repair in progress',kind:'active'});
 }
 for(const index of active)entries.set(index,{label:'Generating',kind:'active'});
 host.replaceChildren();host.hidden=!entries.size;if(!entries.size)return;
 const heading=node('strong','replacement-queue-title','Image replacements');host.append(heading);
 const strip=node('div','replacement-queue-items');
 for(const [index,entry] of entries){
  const pill=node('button','replacement-queue-pill '+entry.kind,'Illustration '+(index+1)+' · '+entry.label);
  pill.type='button';pill.onclick=()=>document.querySelector('[data-image-index="'+index+'"]')?.scrollIntoView({behavior:'smooth',block:'center'});
  strip.append(pill);
 }
 host.append(strip,node('span','replacement-queue-hint',s?.status==='complete'?'Rebuild after selection':'Before video render'));
}

function appendStableArtwork(stage,active,item,previous){
 if(previous&&previous.getAttribute('src')===active.url){previous.onclick=()=>inspect(active.url,item.index);stage.append(previous);return;}
 const img=document.createElement('img');img.alt=item.subject;img.onclick=()=>inspect(active.url,item.index);
 if(previous){
  stage.append(previous);
  img.onload=()=>{if(stage.isConnected)previous.replaceWith(img);};
  img.onerror=()=>{const note=node('span','image-progress-label','Preview unavailable · keeping previous image');stage.append(note);};
 }else stage.append(img);
 img.src=active.url;
}


const optimisticRegenerations=new Map();
function showOptimisticQueue(snapshot){
 if(!snapshot)return snapshot;
 const queued=(snapshot.queued_actions||[]).filter(q=>!q.optimistic);
 for(const [key,item] of optimisticRegenerations){
  if(item.job!==jobId)continue;
  const confirmed=queued.some(q=>q.index===item.index&&q.action===item.action);
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

const TEXT_AREA_KEY='lyricStudioShowTextAreas';
let textAreaDrawing=false;
function textAreasVisible(){try{return localStorage.getItem(TEXT_AREA_KEY)!=='0'}catch{return true}}
function fitToImage(stage,el){
 const img=stage.querySelector('img');if(!img||!img.naturalWidth)return null;
 Object.assign(el.style,{left:img.offsetLeft+'px',top:img.offsetTop+'px',width:img.offsetWidth+'px',height:img.offsetHeight+'px'});
 return img;
}
const TEXT_AREA_ADJUST_KEY='lyricStudioAdjustTextAreas';
function textAreasAdjustable(){try{return localStorage.getItem(TEXT_AREA_ADJUST_KEY)==='1'}catch{return false}}
function attachTextArea(stage,active,item,editable){
 if(!active?.current||!active.text_area||!textAreasVisible())return;
 const frame=node('div','text-area-frame');const area=node('div','text-area-overlay');
 area.append(node('span','text-area-tag',active.text_area.source==='manual'?'Text area · drawn':'Text area'));
 let box=[...active.text_area.box];
 const show=()=>Object.assign(area.style,{left:box[0]*100+'%',top:box[1]*100+'%',width:(box[2]-box[0])*100+'%',height:(box[3]-box[1])*100+'%'});
 show();frame.append(area);stage.append(frame);
 const place=()=>{frame.hidden=!fitToImage(stage,frame)};
 place();stage.addEventListener('load',place,true);new ResizeObserver(place).observe(stage);
 if(!item||!editable||!textAreasAdjustable())return;
 frame.classList.add('adjustable');const handle=node('span','text-area-handle');const startHandle=node('span','text-area-handle start');area.append(startHandle,handle);
 area.title='Drag to move · drag a corner to resize';
 let drag=null;
 area.onpointerdown=e=>{e.preventDefault();e.stopPropagation();area.setPointerCapture(e.pointerId);textAreaDrawing=true;
  drag={resize:e.target===handle?'end':e.target===startHandle?'start':null,x:e.clientX,y:e.clientY,start:[...box],rect:frame.getBoundingClientRect()}};
 area.onpointermove=e=>{if(!drag)return;
  const dx=(e.clientX-drag.x)/drag.rect.width,dy=(e.clientY-drag.y)/drag.rect.height,[l,t,r,b]=drag.start;
  if(drag.resize==='end')box=[l,t,Math.min(1,Math.max(l+.05,r+dx)),Math.min(1,Math.max(t+.05,b+dy))];
  else if(drag.resize==='start')box=[Math.max(0,Math.min(r-.05,l+dx)),Math.max(0,Math.min(b-.05,t+dy)),r,b];
  else{const mx=Math.min(1-r,Math.max(-l,dx)),my=Math.min(1-b,Math.max(-t,dy));box=[l+mx,t+my,r+mx,b+my]}
  show()};
 area.onpointerup=()=>{if(!drag)return;const moved=box.some((v,i)=>Math.abs(v-drag.start[i])>.002);drag=null;textAreaDrawing=false;
  if(moved)action('text-area',{index:item.index,box:box.map(v=>Math.round(v*10000)/10000)});else{gallerySignature='';if(state)renderGallery(state)}};
}
function textAreaButton(stage,item,active,editable){
 return button('Draw text area',()=>drawTextArea(stage,item),!editable||!active?.current||textAreaDrawing);
}
function drawTextArea(stage,item){
 const layer=node('div','text-area-draw');if(!fitToImage(stage,layer))return;
 textAreaDrawing=true;stage.querySelector('.text-area-frame')?.remove();
 const hint=node('span','image-progress-label','Drag over the image to mark where lyrics go · Esc cancels');
 const rect=node('div','text-area-overlay');let start=null;
 const point=e=>{const r=layer.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]};
 const box=e=>{const [x,y]=point(e);return [Math.min(x,start[0]),Math.min(y,start[1]),Math.max(x,start[0]),Math.max(y,start[1])]};
 const show=b=>Object.assign(rect.style,{left:b[0]*100+'%',top:b[1]*100+'%',width:(b[2]-b[0])*100+'%',height:(b[3]-b[1])*100+'%'});
 const finish=()=>{textAreaDrawing=false;document.removeEventListener('keydown',cancel);layer.remove();hint.remove();gallerySignature='';if(state)renderGallery(state)};
 const cancel=e=>{if(e.key==='Escape')finish()};
 layer.onpointerdown=e=>{e.preventDefault();layer.setPointerCapture(e.pointerId);start=point(e);layer.append(rect);show(box(e))};
 layer.onpointermove=e=>{if(start)show(box(e))};
 layer.onpointerup=e=>{if(!start)return;const b=box(e);finish();if(b[2]-b[0]>.03&&b[3]-b[1]>.03)action('text-area',{index:item.index,box:b.map(v=>Math.round(v*10000)/10000)})};
 document.addEventListener('keydown',cancel);stage.append(layer,hint);
}
document.addEventListener('DOMContentLoaded',()=>{
 for(const [id,key,read] of [['showTextAreas',TEXT_AREA_KEY,textAreasVisible],['adjustTextAreas',TEXT_AREA_ADJUST_KEY,textAreasAdjustable]]){
  const toggle=document.getElementById(id);if(!toggle)continue;
  toggle.checked=read();
  toggle.onchange=()=>{try{localStorage.setItem(key,toggle.checked?'1':'0')}catch{}gallerySignature='';if(state)renderGallery(state)};
 }
});

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

const KINETIC_DEFAULTS={pan_speed:.05,backdrop_rate:.6,backdrops:['outline','filled','vertical','echo','giant'],traces:true,geometry:.8,frames:.1,glows:[],glow_strength:.55,glitch:true,text_pulse:.1,thread_shapes:.8};
function kineticSettings(){
 const hidden=document.getElementById('kinetic');let value={};
 try{value=JSON.parse(hidden?.value||'{}')||{}}catch{value={}}
 return {...KINETIC_DEFAULTS,...value};
}
function syncKineticControls(){
 const settings=kineticSettings();
 document.querySelectorAll('[data-kinetic]').forEach(input=>{input.value=settings[input.dataset.kinetic];showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>box.checked=!!settings[box.dataset.kineticFlag]);
 document.querySelectorAll('[data-kinetic-list]').forEach(box=>box.checked=(settings[box.dataset.kineticList]||[]).includes(box.value));
}
function showKineticValue(input){
 const out=document.querySelector(`[data-kinetic-out="${input.dataset.kinetic}"]`);
 if(out)out.value=input.dataset.unit==='%'?Math.round(+input.value*100)+'%':(+input.value).toFixed(3);
}
function storeKineticControls(){
 const settings={};
 document.querySelectorAll('[data-kinetic]').forEach(input=>{settings[input.dataset.kinetic]=+input.value;showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>settings[box.dataset.kineticFlag]=box.checked);
 for(const key of ['backdrops','glows'])settings[key]=[...document.querySelectorAll(`[data-kinetic-list="${key}"]`)].filter(b=>b.checked).map(b=>b.value);
 const hidden=document.getElementById('kinetic');if(hidden)hidden.value=JSON.stringify(settings);
}
window.syncKineticControls=syncKineticControls;
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-kinetic],[data-kinetic-flag],[data-kinetic-list]').forEach(input=>input.addEventListener('input',storeKineticControls));
 syncKineticControls();storeKineticControls();
});
