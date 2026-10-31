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
 const mapping={alignment:1,subjects:2,model:3,illustrations:3,cutouts:3,verification:4,repair:4,'repair-complete':4,review:4,direction:5,render:5,complete:5};
 const actionStep=s.action==='reprompt'?2:s.action==='regenerate'?3:['verify','repair'].includes(s.action)?4:['patch','rerender'].includes(s.action)?5:0;
 const current=actionStep||mapping[s.stage]||0;
 const running=!!s.action||['queued','running','review'].includes(s.status);
 const ready=(s.images||[]).filter(image=>image.variants?.some(v=>v.current)).length;
 const labels=['Timing','Prompts',(s.images?.length?ready+'/'+s.images.length+' Imgs':'Images'),'Review','Video'];
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


function renderProductionStages(s=null){
 // Built off-page and swapped in only when it changed: a running job polls about once a second, and rebuilding
 // every time would throw away the element under the pointer mid-click.
 const shown=$('stages'),host=document.createElement('div');
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
 const labels={alignment:[asrName,alignment==='auto'?'Auto timing':alignment].filter(Boolean).join(' · '),song:castName,meanings:promptName,scenes:promptName,audit:promptName,fit:promptName+' → '+imageName,model:saved?'Used · '+imageName:imageName,illustrations:saved?'Used · '+imageName:imageName,cutouts:'BiRefNet General',review:reviewName,direction:promptName,render:encoder||'H.264'};
 const audio=saved?.audio||$('audio').files[0]?.name||'No audio selected';
 const profile=saved?saved.profile||'Not recorded':localStorage.getItem('lyricStudioProfilesV1Active')||'No saved profile';
 const selectedImage=$('imageModel').selectedOptions[0]?.textContent||'Choose image model';
 $('headerAudio').textContent='Audio · '+audio;$('headerAudio').title=audio;
 $('headerProfile').textContent='Profile · '+profile;$('headerProfile').title=profile;
 $('headerSelectedImage').textContent='Selected image · '+selectedImage;$('headerSelectedImage').title='Selected image model: '+selectedImage;
 // Older runs and single-image prompt rewrites report all prompt work as 'subjects'.
 const stageName=s?.stage==='subjects'?'song':s?.stage;
 const current=s?.status==='complete'?stages.length:stages.indexOf(stageName);
 const startSelect=$('startStep'),substep=$('startSubstep');
 window.headerProgress={current,hasJob:!!jobId,running:!!s?.action||['running','queued'].includes(s?.status),
  queued:s?.status==='queued',stage:stageName};
 PIPELINE_STEPS.forEach((step,index)=>{
  if(index){const arrow=node('span','stage-arrow','->');arrow.setAttribute('aria-hidden','true');host.append(arrow)}
  const option=startSelect?.querySelector(`option[value="${step.value}"]`);
  const pill=node('button','stage');pill.type='button';pill.dataset.step=step.value;
  pill.append(node('span','stage-name',`${index+1}. ${step.name}`));
  const parts=node('span','stage-parts');
  step.stages.forEach((name,i)=>{
   if(i){const arrow=node('span','stage-arrow','→');arrow.setAttribute('aria-hidden','true');parts.append(arrow)}
   const part=node('span','stage-part');
   part.append(node('span','stage-part-name',stageTitle(name)),node('span','stage-model',labels[name]));
   if(saved&&$('imageModel').value&&$('imageModel').value!==image&&['model','illustrations'].includes(name)){
    part.append(node('span','stage-selected','Selected · '+selectedImage));
   }
   if(name===stageName&&s?.status!=='complete')part.classList.add('active');
   else if(stages.indexOf(name)<current)part.classList.add('done');
   // Prompt sub-steps can be restarted from once everything before them is saved.
   if(step.value==='prompts'&&(window.promptSubsteps||[]).includes(name)&&option&&!option.disabled){
    part.classList.add('choosable');part.setAttribute('role','button');
    if(startSelect.value==='prompts'&&(substep.value||'song')===name)part.classList.add('selected');
    part.title=`Start the next generation at Prompts › ${stageTitle(name)}, reusing the saved prompting work before it.`;
    part.onclick=event=>{
     event.stopPropagation();
     const chosen=startSelect.value==='prompts'&&(substep.value||'song')===name;
     startSelect.value=chosen?'beginning':'prompts';startSelect.dispatchEvent(new Event('change',{bubbles:true}));
     substep.value=chosen||name==='song'?'':name;renderProductionStages(s);
    };
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
  else if(step.stages.includes(stageName)){pill.classList.add('active');pill.setAttribute('aria-current','step')}
  const available=option&&!option.disabled;
  pill.setAttribute('aria-disabled',String(!available));if(!available)pill.classList.add('unavailable');
  if(startSelect?.value===step.value)pill.classList.add('selected');
  pill.setAttribute('aria-pressed',String(startSelect?.value===step.value));
  pill.title=`${step.name}: ${step.stages.map(stageTitle).join(', ')} · ${models}
`+(available?`Click to start the next generation at ${step.name}.`:`${step.name} needs earlier steps finished first.`);
  pill.onclick=()=>{if(!startSelect||!available)return;startSelect.value=startSelect.value===step.value?'beginning':step.value;startSelect.dispatchEvent(new Event('change',{bubbles:true}));renderProductionStages(s)};
  host.append(pill);
 });
 if(host.innerHTML!==shown.innerHTML)shown.replaceChildren(...host.childNodes);
 syncStartAtStage();
}
const PIPELINE_STEPS=[
 {value:'timing',name:'Timing',stages:['alignment']},
 {value:'prompts',name:'Prompts',stages:['song','meanings','scenes','audit','fit']},
 {value:'images',name:'Images',stages:['model','illustrations','cutouts']},
 {value:'review',name:'Review',stages:['review']},
 {value:'render',name:'Video',stages:['direction','render']}];
const stageTitle=name=>({audit:'Check'})[name]||name[0].toUpperCase()+name.slice(1);
function syncStartAtStage(){
 const button=$('startAtStage'),select=$('startStep');if(!button||!select)return;
 const step=PIPELINE_STEPS.find(step=>step.value===select.value);
 const sub=step?.value==='prompts'?$('startSubstep')?.value||'':'';
 const name=step?step.name+(sub?' › '+stageTitle(sub):''):'';
 const progress=window.headerProgress||{};
 // Starting where the last run stopped, or at a step it never reached, picks up its work: resume.
 const position=step?stages.indexOf(sub||step.stages[0]):0;
 const resume=!!step&&progress.hasJob&&progress.current>=0&&progress.current<stages.length&&position>=progress.current;
 let label,kind,help;
 if(!progress.hasJob){label='Start new generation';kind='';help='Start a new generation from the beginning.'}
 else if(resume){label='Resume from '+name;kind='resume';help=`Continue from ${name}, where the last run stopped, keeping everything it finished.`}
 else if(!step||step.value==='timing'){label='Clear and Regenerate';kind='regenerate';help=step?'Redo everything from word timing; existing artwork is replaced.':'Start over in a new session with these settings.'}
 else{label='Regenerate from '+name;kind='regenerate';help=`Redo ${name} and every step after it; earlier steps are reused.`}
 if(progress.running){
  const stage=stages.includes(progress.stage)?stageTitle(progress.stage):'';
  label=progress.queued?'Queued':'Running';kind='running';help=`A run is in progress${stage?' ('+stage+')':''}; cancel it to start another.`;
 }
 const spinner=node('span','busy-spinner');spinner.setAttribute('aria-hidden','true');
 button.replaceChildren(...(kind==='running'?[spinner,label]:[label+' ↗']));button.title=help;
 button.setAttribute('aria-busy',String(kind==='running'));
 for(const name of ['resume','regenerate','running'])button.classList.toggle(name,kind===name);
 button.disabled=kind==='running'||$('generate').disabled;
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
 if(['verify','repair'].includes(s?.action)&&['subjects','song','meanings','scenes','audit','fit','model','illustrations','cutouts','repair'].includes(s?.action_stage)){
  for(const index of waiting)entries.set(index,{label:['subjects','song','meanings','scenes','audit','fit'].includes(s.action_stage)?'Revising prompt':'Repair in progress',kind:'active'});
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

const KINETIC_DEFAULTS={camera:'pan',pan_speed:.05,backdrop_rate:.6,backdrops:['outline','filled','vertical','echo','giant'],traces:true,geometry:.8,frames:.1,glows:['drums','other','bass'],glow_words:.15,glow_strength:.55,glitch:true,text_pulse:0,word_shapes:0,drum_reactivity:.8,chorus_fx:.75,fade:true};
function kineticSettings(){
 const hidden=document.getElementById('kinetic');let value={};
 try{value=JSON.parse(hidden?.value||'{}')||{}}catch{value={}}
 delete value.thread_shapes;
 return {...KINETIC_DEFAULTS,...value};
}
function syncKineticControls(){
 const settings=kineticSettings();
 document.querySelectorAll('[data-kinetic]').forEach(input=>{input.value=settings[input.dataset.kinetic];showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>box.checked=!!settings[box.dataset.kineticFlag]);
 document.querySelectorAll('[data-kinetic-list]').forEach(box=>{const list=settings[box.dataset.kineticList];box.checked=list==null||list.includes(box.value)});
 document.querySelectorAll('[data-kinetic-choice]').forEach(select=>select.value=settings[select.dataset.kineticChoice]);
 syncCameraMode();
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
 const pan=document.querySelector('[data-kinetic="pan_speed"]');if(pan)pan.disabled=flow==='realtime'&&camera==='still';
}
function showKineticValue(input){
 const out=document.querySelector(`[data-kinetic-out="${input.dataset.kinetic}"]`);
 if(out)out.value=input.dataset.unit==='%'?Math.round(+input.value*100)+'%':(+input.value).toFixed(3);
}
function storeKineticControls(){
 const settings={};
 document.querySelectorAll('[data-kinetic]').forEach(input=>{settings[input.dataset.kinetic]=+input.value;showKineticValue(input)});
 document.querySelectorAll('[data-kinetic-flag]').forEach(box=>settings[box.dataset.kineticFlag]=box.checked);
 document.querySelectorAll('[data-kinetic-choice]').forEach(select=>settings[select.dataset.kineticChoice]=select.value);
 for(const key of ['backdrops','glows'])settings[key]=[...document.querySelectorAll(`[data-kinetic-list="${key}"]`)].filter(b=>b.checked).map(b=>b.value);
 const scenes=[...document.querySelectorAll('[data-kinetic-list="scenes"]')];
 if(scenes.length)settings.scenes=scenes.filter(b=>b.checked).map(b=>b.value);
 const hidden=document.getElementById('kinetic');if(hidden)hidden.value=JSON.stringify(settings);
 syncCameraMode();
}
window.syncKineticControls=syncKineticControls;
function sceneSampleQuery(id){
 const value=key=>document.getElementById(key)?.value;
 const query={scene:id,v:'scene-samples-1'};
 for(const [key,field] of [['font_family','fontFamily'],['font_style','fontStyle'],['font_scale','fontScale']])if(value(field))query[key]=value(field);
 return '/api/scene-preview?'+new URLSearchParams(query);
}
function renderSceneEffects(scenes){
 const group=document.getElementById('sceneEffects');if(!group||!Array.isArray(scenes))return;
 group.classList.add('scene-choices');
 group.replaceChildren(...scenes.map(scene=>{
  const card=document.createElement('div');card.className='scene-choice';
  const label=document.createElement('label');label.className='check-toggle';label.title=scene.description||'';
  const box=document.createElement('input');box.type='checkbox';box.value=scene.id;box.dataset.kineticList='scenes';
  box.addEventListener('input',()=>{if(!group.querySelector('input:checked'))box.checked=true;storeKineticControls()});
  label.append(box,scene.name);
  // An animated sample of the scene, rendered (and cached) on first view.
  const sample=document.createElement('img');sample.className='scene-thumbnail';sample.loading='lazy';
  sample.alt=scene.name+' animated sample';sample.title=scene.description||'';sample.dataset.scene=scene.id;sample.src=sceneSampleQuery(scene.id);
  sample.addEventListener('click',()=>{box.checked=!box.checked;box.dispatchEvent(new Event('input'))});
  card.append(label,sample);return card;
 }));
 syncKineticControls();
}
function refreshSceneSamples(){document.querySelectorAll('.scene-thumbnail').forEach(img=>{img.src=sceneSampleQuery(img.dataset.scene)})}
window.refreshSceneSamples=refreshSceneSamples;
window.renderSceneEffects=renderSceneEffects;
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-kinetic],[data-kinetic-flag],[data-kinetic-list],[data-kinetic-choice]').forEach(input=>input.addEventListener('input',storeKineticControls));
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
new MutationObserver(()=>document.querySelectorAll('#gallery .image-stage img').forEach(classifyGalleryImage))
 .observe($('gallery'),{childList:true,subtree:true});
