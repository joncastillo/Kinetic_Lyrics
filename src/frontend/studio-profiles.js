// Saved profiles, model pickers, speech models and the GPU-fit helpers.
const VOCAL_LANGUAGES={"af": "afrikaans", "sq": "albanian", "am": "amharic", "ar": "arabic", "hy": "armenian", "as": "assamese", "az": "azerbaijani", "ba": "bashkir", "eu": "basque", "be": "belarusian", "bn": "bengali", "bs": "bosnian", "br": "breton", "bg": "bulgarian", "yue": "cantonese", "ca": "catalan", "zh": "chinese", "hr": "croatian", "cs": "czech", "da": "danish", "nl": "dutch", "en": "english", "et": "estonian", "fo": "faroese", "fi": "finnish", "fr": "french", "gl": "galician", "ka": "georgian", "de": "german", "el": "greek", "gu": "gujarati", "ht": "haitian creole", "ha": "hausa", "haw": "hawaiian", "he": "hebrew", "hi": "hindi", "hu": "hungarian", "is": "icelandic", "id": "indonesian", "it": "italian", "ja": "japanese", "jw": "javanese", "kn": "kannada", "kk": "kazakh", "km": "khmer", "ko": "korean", "lo": "lao", "la": "latin", "lv": "latvian", "ln": "lingala", "lt": "lithuanian", "lb": "luxembourgish", "mk": "macedonian", "mg": "malagasy", "ms": "malay", "ml": "malayalam", "mt": "maltese", "mi": "maori", "mr": "marathi", "mn": "mongolian", "my": "myanmar", "ne": "nepali", "no": "norwegian", "nn": "nynorsk", "oc": "occitan", "ps": "pashto", "fa": "persian", "pl": "polish", "pt": "portuguese", "pa": "punjabi", "ro": "romanian", "ru": "russian", "sa": "sanskrit", "sr": "serbian", "sn": "shona", "sd": "sindhi", "si": "sinhala", "sk": "slovak", "sl": "slovenian", "so": "somali", "es": "spanish", "su": "sundanese", "sw": "swahili", "sv": "swedish", "tl": "tagalog", "tg": "tajik", "ta": "tamil", "tt": "tatar", "te": "telugu", "th": "thai", "bo": "tibetan", "tr": "turkish", "tk": "turkmen", "uk": "ukrainian", "ur": "urdu", "uz": "uzbek", "vi": "vietnamese", "cy": "welsh", "yi": "yiddish", "yo": "yoruba"};
const PROFILE_KEY='lyricStudioProfilesV1';

const ACTIVE_PROFILE_KEY=PROFILE_KEY+'Active';
let preferredVisionModel=null,profileAudioPath='',profileAudioName='',profileAudioFile=null,audioRestoreVersion=0;
const AUDIO_DRAFT_KEY='lyricStudioAudioDraftV1';
let audioSavePromise=null,audioSaveFile=null;
function profileAudioStatus(message,missing=false){const el=$('profileAudioStatus');if(el){el.textContent=message;el.style.color=missing?'var(--warn)':''}}
function rememberAudioDraft(){try{localStorage.setItem(AUDIO_DRAFT_KEY,JSON.stringify({audio_path:profileAudioPath,audio_name:profileAudioName}))}catch{toast('The audio is saved locally, but this browser could not remember its path for reload.')}}
function readAudioDraft(){try{const value=JSON.parse(localStorage.getItem(AUDIO_DRAFT_KEY)||'null');return value&&typeof value.audio_path==='string'?value:null}catch{return null}}
async function persistProfileAudio(){
 const file=$('audio').files[0];
 if(!file)return;
 if(file===profileAudioFile&&profileAudioPath){rememberAudioDraft();return}
 if(audioSaveFile===file&&audioSavePromise)return audioSavePromise;
 audioSaveFile=file;
 const saving=(async()=>{
  profileAudioStatus('Saving audio for reload…');
  const form=new FormData();form.append('audio',file);
  const saved=await api('/api/profile-audio',form);
  if($('audio').files[0]!==file)throw Error('Audio changed while saving.');
  profileAudioPath=saved.path;profileAudioName=file.name;profileAudioFile=file;
  rememberAudioDraft();profileAudioStatus('Saved audio: '+profileAudioPath);
 })();
 audioSavePromise=saving;
 try{await saving}finally{if(audioSavePromise===saving){audioSavePromise=null;audioSaveFile=null}}
}
async function restoreProfileAudio(settings){
 if(!Object.hasOwn(settings,'audio_path'))return;
 const version=++audioRestoreVersion;
 profileAudioPath=typeof settings.audio_path==='string'?settings.audio_path:'';
 profileAudioName=typeof settings.audio_name==='string'?settings.audio_name:'';
 rememberAudioDraft();
 profileAudioFile=null;$('audio').value='';
 if(audioObjectUrl){URL.revokeObjectURL(audioObjectUrl);audioObjectUrl=''}
 $('audioPreview').pause();$('audioPreview').removeAttribute('src');$('audioPreview').hidden=true;
 profileAudioStatus('');if(!profileAudioPath)return;
 const path=profileAudioPath;profileAudioStatus('Loading saved audio…');
 try{
  // A connection that is not up yet (the studio restarting, the page opened early) gets a few quiet retries
  // before the saved audio is declared unavailable.
  let response;
  for(let attempt=0;;attempt++){
   try{response=await fetch('/api/profile-audio?path='+encodeURIComponent(path));break}
   catch(e){if(attempt>=3||version!==audioRestoreVersion)throw e;await new Promise(done=>setTimeout(done,1200*(attempt+1)))}
  }
  if(version!==audioRestoreVersion)return;
  if(!response.ok){const error=await response.json();throw Error(error.error||'Saved audio could not be loaded')}
  const blob=await response.blob();if(version!==audioRestoreVersion)return;
  const file=new File([blob],profileAudioName||path.split(/[\\/]/).pop(),{type:blob.type});
  const transfer=new DataTransfer();transfer.items.add(file);$('audio').files=transfer.files;profileAudioFile=$('audio').files[0];
  audioObjectUrl=URL.createObjectURL(file);$('audioPreview').src=audioObjectUrl;$('audioPreview').hidden=false;
  profileAudioStatus('Saved audio: '+path);
 }catch(e){if(version===audioRestoreVersion)profileAudioStatus('Audio unavailable: '+(e instanceof TypeError?'the studio did not answer. Reconnect to try again.':e.message),true)}
}
function restoreVisionSelection(){
 if(preferredVisionModel===null||!$('visionModel'))return;
 const available=[...$('visionModel').options].some(o=>o.value===preferredVisionModel);
 if(available){
  $('visionModel').value=preferredVisionModel;
 }else if(preferredVisionModel){
  $('visionModel').add(new Option(preferredVisionModel, preferredVisionModel));
  $('visionModel').value=preferredVisionModel;
 }
 gallerySignature='';if(state)renderGallery(state);
}

const PROFILE_FIELDS=['appearance','video_generation','video_model','text_animation','audio_mode','text_pool','lettering_styles','reading_flow','stage_pictures','kinetic','effect_speeds','effect_intensities','font_family','font_style','font_scale','auto_accept','entrance_pool','exit_pool','entrance_effect','exit_effect','artwork_mode','ai_model','particle_speed','image_model','vision_model','project_id','asr_model','alignment_model','reference_prompt','cast_reference','style','image_instructions','instructions','type_effect','particle_intensity','language','auto_verify','review_references','repaint_references','auto_repair','review_threshold','cinematic','resolution','lines','steps','video_upscale','picture_kinds','end_frame_model','end_frame_review','depth_model','encoder','cache'];
let imageModels=[],audioModels=[],backendReady=false,sessionRegenerationSupported=false,imageInstructionsSupported=false;
const DEFAULT_PROFILE_NAME='Mucha · Bright & Flowing';
const DEFAULT_REFERENCE='/assets/reference_female_1.jpeg';
const LEGACY_REFERENCE='/assets/reference_female_2.jpeg';
const DEFAULT_REFERENCE_PROMPT='Elegant contemporary 2.5D digital illustration, refined semi-realistic editorial art style, clean smooth digital painting, crisp confident edges, polished shading, gentle facial-detail rendering, soft diffused lighting, vibrant color harmony. sophisticated modern illustration, Hand-painted finish.';
const DEFAULT_PROFILE={version:1,settings:{artwork_mode:'cutout',ai_model:'auto',image_model:'Qwen/Qwen-Image-2.1',vision_model:'',asr_model:'qwen3-asr-1.7b',alignment_model:'auto',reference_prompt:DEFAULT_REFERENCE_PROMPT,style:'',image_instructions:'',story_prompt:'',instructions:'',type_effect:'mixed',particle_intensity:'1',language:'auto',auto_verify:true,auto_repair:true,review_threshold:"50",cinematic:true,resolution:'720p',lines:'2',steps:'50',encoder:'h264_nvenc',cache:'',image_seed:'',randomize_seed:true,reference_asset:DEFAULT_REFERENCE}};
async function initializeProfiles(){
 if(!window.profileChoicePersistenceBound){
  window.profileChoicePersistenceBound=true;
  // Every edit in the creative brief, including image prompt instructions, is kept in the active profile.
  let pendingProfileSave=0;
  const storeActiveProfile=()=>{
   clearTimeout(pendingProfileSave);
   pendingProfileSave=setTimeout(()=>{
    try{
     const name=localStorage.getItem(ACTIVE_PROFILE_KEY)||$('profileList').value;
     const profiles=getProfiles();if(!name||!profiles[name])return;
     profiles[name].settings={...profiles[name].settings,...profileSettings()};
     localStorage.setItem(PROFILE_KEY,JSON.stringify(profiles));
    }catch{toast('The profile setting could not be saved in this browser.');}
   },400);
  };
  // Listen on the document: some controls, such as effect previews, sit outside the form and update hidden fields.
  // Choosing a session or profile loads settings rather than editing them, so it is not saved over the profile.
  const loaders=new Set(['jobs','profileList','profileName','profileFile']);
  for(const type of ['input','change'])document.addEventListener(type,event=>{if(!loaders.has(event.target.id))storeActiveProfile()});
 }

 try{
  const profiles=getProfiles();
  for(const profile of Object.values(profiles))if(isImportedSongMeaning(profile?.settings?.image_instructions))profile.settings.image_instructions='';
  if(!Object.hasOwn(profiles,DEFAULT_PROFILE_NAME))profiles[DEFAULT_PROFILE_NAME]=JSON.parse(JSON.stringify(DEFAULT_PROFILE));
  // The bundled profile's reference prompt was updated; keep any wording the user wrote themselves.
  const bundled=profiles[DEFAULT_PROFILE_NAME].settings;
  if(!localStorage.getItem(PROFILE_KEY+'ReferencePromptV2')){
   if(!bundled.reference_prompt||bundled.reference_prompt==='Delicate linework, elegant proportions, expressive faces, flowing hair, and soft painterly shading inspired by Alphonse Mucha.')bundled.reference_prompt=DEFAULT_PROFILE.settings.reference_prompt;
   localStorage.setItem(PROFILE_KEY+'ReferencePromptV2','1');
  }
  if(!localStorage.getItem(PROFILE_KEY+'ReferencePromptV3')){
   const previous='Delicate linework, elegant proportions, expressive faces, flowing hair, and soft painterly shading inspired by Alphonse Mucha. The images are modern, upbeat, and resembles anime.';
   if(!bundled.reference_prompt||bundled.reference_prompt===previous)bundled.reference_prompt=DEFAULT_REFERENCE_PROMPT;
   if(!bundled.reference_asset||[LEGACY_REFERENCE,'/assets/reference_default.jpeg'].includes(bundled.reference_asset))bundled.reference_asset=DEFAULT_REFERENCE;
   localStorage.setItem(PROFILE_KEY+'ReferencePromptV3','1');
  }
  if(!localStorage.getItem(PROFILE_KEY+'ReferencePromptV4')){
   // Profiles still holding the previous default get the new one; wording the user wrote themselves is kept.
   const previous='Delicate linework, elegant proportions, expressive faces, flowing hair, graceful transparent fabric folds, and soft painterly shading inspired by Alphonse Mucha. Modern, fun, happy, sexy, upbeat.';
   for(const profile of Object.values(profiles))if(profile?.settings?.reference_prompt===previous)profile.settings.reference_prompt=DEFAULT_REFERENCE_PROMPT;
   localStorage.setItem(PROFILE_KEY+'ReferencePromptV4','1');
  }
  if(!localStorage.getItem(PROFILE_KEY+'ApprovedLookV1')){
   // The approved look becomes the default: profiles still holding the old default text or mood move to it; wording the user wrote themselves is kept.
   const previous='Delicate linework and soft painterly shading. For humans: expressive faces, flowing hair, graceful transparent fabric folds. Visual style & mood: Modern, fun, happy, bright, uplifting mood.';
   const moods=['Bright, uplifting mood; emphasis on flowing fabric, long flowing hair, graceful movement and luminous color. Expressive editorial typography with letters that shatter, melt and flow.','Bright, uplifting mood; flowing fabric, long flowing hair, graceful movement and luminous color.'];
   for(const profile of Object.values(profiles)){
    if(profile?.settings?.reference_prompt===previous)profile.settings.reference_prompt=DEFAULT_REFERENCE_PROMPT;
    if(moods.includes(profile?.settings?.style))profile.settings.style='';
   }
   localStorage.setItem(PROFILE_KEY+'ApprovedLookV1','1');
  }
  if(!localStorage.getItem(PROFILE_KEY+'DigitalLookV1')){
   // The default style drops its ink and sketch words: the built-in profile moves to it; a profile the user saved keeps its wording.
   if(bundled.reference_prompt==='Elegant contemporary 2.5D digital illustration, refined semi-realistic editorial art style, highly detailed flowing linework, sophisticated ink-and-watercolor fusion, subtle sketch lines, expressive brushstrokes, layered translucent textures, gentle facial-detail rendering, soft diffused lighting, vibrant color harmony. sophisticated modern illustration, Hand-painted finish.')bundled.reference_prompt=DEFAULT_REFERENCE_PROMPT;
   localStorage.setItem(PROFILE_KEY+'DigitalLookV1','1');
  }
  if(!localStorage.getItem(PROFILE_KEY+'QwenGpuDefaultsV1')){
   profiles[DEFAULT_PROFILE_NAME].settings.image_model='Qwen/Qwen-Image-Edit-2511';profiles[DEFAULT_PROFILE_NAME].settings.steps='40';
   localStorage.setItem(PROFILE_KEY+'QwenGpuDefaultsV1','1');
  }
  // Only models that take reference pictures are offered: saved profiles naming another one get the default
  if(!localStorage.getItem(PROFILE_KEY+'ReferenceModelsV1')){
   const offered=['black-forest-labs/FLUX.2-klein-4B','black-forest-labs/FLUX.2-klein-9B','Qwen/Qwen-Image-Edit-2511','Qwen/Qwen-Image-2.1'];
   for(const profile of Object.values(profiles))if(profile?.settings?.image_model&&!offered.includes(profile.settings.image_model)){
    profile.settings.image_model='Qwen/Qwen-Image-Edit-2511';profile.settings.steps='40'}
   localStorage.setItem(PROFILE_KEY+'ReferenceModelsV1','1');
  }
  // Qwen Image Edit 2511 replaces 2509: saved profiles move to it
  if(!localStorage.getItem(PROFILE_KEY+'QwenEdit2511V1')){
   for(const profile of Object.values(profiles))if(profile?.settings?.image_model==='Qwen/Qwen-Image-Edit-2509')profile.settings.image_model='Qwen/Qwen-Image-Edit-2511';
   localStorage.setItem(PROFILE_KEY+'QwenEdit2511V1','1');
  }
  // Qwen Image 2.1 becomes the default: the built-in profile moves to it (a profile the user saved keeps its choice)
  if(!localStorage.getItem(PROFILE_KEY+'QwenImage21V1')){
   if(profiles[DEFAULT_PROFILE_NAME]?.settings){profiles[DEFAULT_PROFILE_NAME].settings.image_model='Qwen/Qwen-Image-2.1';profiles[DEFAULT_PROFILE_NAME].settings.steps='40'}
   localStorage.setItem(PROFILE_KEY+'QwenImage21V1','1');
  }
  localStorage.setItem(PROFILE_KEY,JSON.stringify(profiles));
  localStorage.setItem('lyricStudioDefaultProfileV1','1');
  const activeName=localStorage.getItem(ACTIVE_PROFILE_KEY);
  const selectedName=activeName&&Object.hasOwn(profiles,activeName)?activeName:DEFAULT_PROFILE_NAME;
  if(!localStorage.getItem(PROFILE_KEY+'RequestedReferenceImageV1')){
   profiles[selectedName].settings.reference_prompt=DEFAULT_REFERENCE_PROMPT;
   profiles[selectedName].settings.reference_asset=DEFAULT_REFERENCE;
   localStorage.setItem(PROFILE_KEY,JSON.stringify(profiles));
   localStorage.setItem(PROFILE_KEY+'RequestedReferenceImageV1','1');
  }
  refreshProfiles(selectedName);$('profileName').value=selectedName;
  const previousAudio=profiles[activeName]?.settings;
  const audioDraft=readAudioDraft()??(typeof previousAudio?.audio_path==='string'?{audio_path:previousAudio.audio_path,audio_name:previousAudio.audio_name||''}:null);
  await applyProfile({...profiles[selectedName].settings,...(audioDraft||{})});
  localStorage.setItem(ACTIVE_PROFILE_KEY,selectedName);refreshProfiles(selectedName);
 }catch(e){toast(e.message)}
}
async function restoreProfileReference(asset){if(asset==='/assets/reference_default.jpeg')asset=LEGACY_REFERENCE;if(![DEFAULT_REFERENCE,LEGACY_REFERENCE].includes(asset))throw Error('Unknown bundled profile reference');if(!backendReady)return;const response=await fetch(asset);if(!response.ok)throw Error('The bundled reference image could not be loaded');const blob=await response.blob();const filename=asset.split('/').at(-1);refs.forEach(r=>URL.revokeObjectURL(r.url));refs=[{file:new File([blob],filename,{type:blob.type||'image/png'}),url:URL.createObjectURL(blob),asset}];showRefs();}

function modelHelp(){const m=imageModels.find(m=>m.id===$('imageModel').value);if(!m)return;$('modelHelp').textContent=`${m.description} ${m.license}. Allow ~${m.disk_gb} GB disk space for first download.`;$('modelLink').href='https://huggingface.co/'+m.id;}
function initModels(cfg){initParticleEffects(cfg);window.initVideo?.(cfg);promptRegenerationSupported=!!cfg.prompt_regeneration;sessionRegenerationSupported=!!cfg.new_session_regeneration_supported;imageInstructionsSupported=!!cfg.image_instructions_supported;initSpeech(cfg);setupModelControls(cfg);backendReady=!!cfg.image_models;$('generate').disabled=!backendReady;if(backendReady&&!refs.length)restoreProfileReference(DEFAULT_REFERENCE).catch(e=>console.warn(e));imageModels=cfg.image_models||[{id:cfg.model,name:'Current model (restart to change)',description:'The studio backend needs a restart after the active job finishes.',license:'',disk_gb:40}];if(!backendReady){const note=document.createElement('p');note.className='compatibility-note';note.textContent='Updated controls are installed. Restart Kinetic Lyrics after this job finishes to enable model selection and rebuilds.';$('studioCompatibility').append(note);$('imageModel').disabled=true;}$('imageModel').replaceChildren(...imageModels.map(m=>new Option(m.name,m.id)));$('imageModel').value=cfg.model;modelHelp();$('imageModel').onchange=()=>{const m=imageModels.find(m=>m.id===$('imageModel').value);if(m)$('steps').value=m.steps;modelHelp()};try{const saved=localStorage.getItem('lyricStudioModelFolder');if(saved)$('cache').value=saved}catch{}$('cache').onchange=()=>{try{localStorage.setItem('lyricStudioModelFolder',$('cache').value)}catch{toast('Could not remember the model folder.')}};}
function getProfiles(){const value=JSON.parse(localStorage.getItem(PROFILE_KEY)||'{}');return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}
function refreshProfiles(selected=''){try{const profiles=getProfiles();$('profileList').replaceChildren(new Option('Choose a profile',''),...Object.keys(profiles).sort().map(n=>new Option(n,n)));$('profileList').value=selected;const has=!!$('profileList').value;$('loadProfile').disabled=!has;$('deleteProfile').disabled=!has;}catch{toast('Profiles could not be read from browser storage.');}}
function profileSettings(){
 const settings={};
 for(const name of PROFILE_FIELDS){
  const el=$('jobForm').elements.namedItem(name);
  if(el)settings[name]=el.type==='checkbox'?el.checked:el.value;
 }
 settings.ai_model=$('aiModel')?$('aiModel').value:'auto';
 settings.image_model=$('imageModel')?$('imageModel').value:'';
 settings.vision_model=preferredVisionModel??($('visionModel')?$('visionModel').value:'');
 settings.project_id=($('projectId')?$('projectId').value:'')||(window.jobId||'');
 if(profileAudioPath){
  settings.audio_path=profileAudioPath;
  settings.audio_name=profileAudioName;
 }
 const bundled=refs.find(r=>r.asset);
 if(bundled)settings.reference_asset=bundled.asset;
 return settings;
}
async function applyProfile(settings){
 settings={...settings,picture_kinds:'static'};
 if(!settings||typeof settings!=='object'||Array.isArray(settings))throw Error('Invalid profile settings');
 queueMicrotask(()=>window.syncVideoControls?.());
 settings={font_family:'auto',font_style:'auto',font_scale:1.25,text_pool:['directed','highlight','karaoke','slide','fade','mask-rise','cartoon-pop','none'],...settings};

 if($('autoAccept'))$('autoAccept').checked=settings.auto_accept===true;
 if($('textAnimation'))$('textAnimation').value=[...$('textAnimation').options].some(option=>option.value===settings.text_animation)?settings.text_animation:'directed';
 if($('audioMode'))$('audioMode').value=settings.audio_mode==='karaoke'?'karaoke':'original';
 for(const phase of ['entrance','exit']){
  const el=$(phase+'Effect');const value=settings[phase+'_effect']??'legacy';
  if(el)el.value=[...el.options].some(o=>o.value===String(value))?String(value):'none';
 }
 for(const name of PROFILE_FIELDS){
  const el=$('jobForm').elements.namedItem(name);
  if(!el||!Object.hasOwn(settings,name))continue;
  let value=((name.endsWith('_pool')||name==='lettering_styles')&&Array.isArray(settings[name]))||((name==='kinetic'||name==='effect_speeds'||name==='effect_intensities')&&typeof settings[name]==='object'&&settings[name])?JSON.stringify(settings[name]):settings[name];
  if(name==='image_instructions'&&isImportedSongMeaning(value))value='';
  if(name==='lettering_styles')queueMicrotask(()=>window.syncLetteringChecks?.());
  if(name==='kinetic'||name==='reading_flow')queueMicrotask(()=>window.syncKineticControls?.());
  if(name==='picture_kinds')queueMicrotask(()=>window.showPictureKinds?.());
  if(name==='appearance')queueMicrotask(()=>window.syncAppearance?.());
  if(el.type==='checkbox'){
   if(typeof value!=='boolean')throw Error('Invalid checkbox setting: '+name);
   el.checked=value;
  }else{
   if(typeof value!=='string'&&typeof value!=='number')throw Error('Invalid setting: '+name);
   if(el.tagName==='SELECT'&&![...el.options].some(o=>o.value===String(value))){
    if(el.id==='aiModel'||el.id==='visionModel'){
     el.add(new Option(String(value),String(value)));
    }else{
     continue;
    }
   }
   el.value=String(value);
  }
 }
 restoreParticlePools(settings);if($('textAnimation').value==='ai'&&!window.aiTypographyAvailable)$('textAnimation').value='mixed';if(window.refreshTypographyLabels)refreshTypographyLabels();
 if(typeof settings.ai_model==='string'&&$('aiModel')){
  const prompt=promptingModelSelection(settings.ai_model);
  for(const option of [...$('aiModel').options])if(isVisionModel(option.value))option.remove();
  if(![...$('aiModel').options].some(o=>o.value===prompt)){
   $('aiModel').add(new Option(prompt,prompt));
  }
  $('aiModel').value=prompt;
 }
 if(typeof settings.vision_model==='string'){
  preferredVisionModel=settings.vision_model;
  restoreVisionSelection();
 }
 const targetProject=(typeof settings.project_id==='string'&&settings.project_id)||window.jobId||($('projectId')?$('projectId').value:'')||($('jobs')?$('jobs').value:'')||'';
 if($('projectId'))$('projectId').value=targetProject;
 await updateProjectPipelineStatus(targetProject);
 await restoreProfileAudio(settings);
 syncValidationControls();modelHelp();lineCount();updateDensity();updateSpeed();speechInfo();refreshSidebarLabels();
 await restoreProfileReference(settings.reference_asset||DEFAULT_REFERENCE);
}

let projectStatusRequestVersion=0;
async function updateProjectPipelineStatus(projId,options={}){
 const requestVersion=++projectStatusRequestVersion;
 const card=$('projectPipelineCard');
 const nameLabel=$('projectNameLabel');
 const badge=$('projectStepBadge');
 const startSelect=$('startStep');
 
 if(!projId){
  projId=(window.jobId||($('projectId')?$('projectId').value:'')||($('jobs')?$('jobs').value:'')||'').trim();
 }
 const prevVal=startSelect?startSelect.value:'beginning';

 const resetStepsCard=()=>{
  if(!card)return;
  card.querySelectorAll('.pipe-step').forEach(s=>{
   s.dataset.status='pending';
   s.style.background='#ffffff06';
   s.style.borderColor='#ffffff22';
   s.style.color='var(--muted)';
   s.style.cursor='default';
   s.style.outline='none';
   s.onclick=null;
   const icon=s.querySelector('.step-icon');
   if(icon)icon.textContent='○';
   const label=s.querySelector('.step-name');if(label)label.textContent=['Timing','Prompts','Images','Review','Kinetic Text'][+s.dataset.step-1];
  });
 };

 if(!projId){
  resetStepsCard();
  if(startSelect){
   for(const opt of startSelect.options){
    opt.disabled=(opt.value!=='beginning');
   }
   startSelect.value='beginning';
  }
  if(nameLabel)nameLabel.textContent='No project linked';
  if(badge){badge.textContent='New';badge.style.color='var(--muted)';}
  if($('audio'))$('audio').required=true;
  updateStepHelp();
  return;
 }
 
 try{
  const st=await api(`/api/projects/${encodeURIComponent(projId)}/status`);
  if(requestVersion!==projectStatusRequestVersion)return;
  if(!st||!st.exists){
   resetStepsCard();
   if(startSelect){
    for(const opt of startSelect.options){
     opt.disabled=(opt.value!=='beginning');
    }
    startSelect.value='beginning';
   }
   if(nameLabel)nameLabel.textContent='Project: '+projId+' (not found)';
   if(badge){badge.textContent='Missing';badge.style.color='var(--error)';}
   if($('audio'))$('audio').required=true;
   updateStepHelp();
   return;
  }
  if(nameLabel)nameLabel.textContent='Project: '+projId;
  window.promptSubsteps=st.prompt_substeps||[];
  if($('projectId'))$('projectId').value=projId;
  resetStepsCard();
  
  const setStepDone=(stepNum,label)=>{
   if(!card)return;
   const el=card.querySelector(`.pipe-step[data-step="${stepNum}"]`);
   if(el){
    el.style.background='#ffffff0a';
    el.style.borderColor='#ffffff38';
    el.style.color='#a6f3c1';
    const icon=el.querySelector('.step-icon');
    if(icon)icon.textContent='✓';
    if(label){
     const nm=el.querySelector('.step-name');
     if(nm)nm.textContent=label;
    }
   }
  };

  if(startSelect){
   const ob=startSelect.querySelector('option[value="beginning"]');if(ob)ob.disabled=false;
   const o1=startSelect.querySelector('option[value="timing"]');if(o1)o1.disabled=!(st.has_audio||st.exists);
   const o2=startSelect.querySelector('option[value="prompts"]');if(o2)o2.disabled=!st.has_timings;
   const o3=startSelect.querySelector('option[value="images"]');if(o3)o3.disabled=!(st.has_prompts&&st.has_timings);
   const o4=startSelect.querySelector('option[value="review"]');if(o4)o4.disabled=!st.has_images;
   const o5=startSelect.querySelector('option[value="render"]');if(o5)o5.disabled=!st.has_images||kineticSettings().overlay_text===false;
   // AI video and in-scene lyric spots run on the finished images as jobs of their own
   const o8=startSelect.querySelector('option[value="video"]');if(o8)o8.disabled=!st.has_images;
   const o9=startSelect.querySelector('option[value="scene-scan"]');if(o9)o9.disabled=!st.has_images||!window.sceneLyricsEnabled?.();
  }

  if(st.has_timings)setStepDone(1,'Timing');
  if(st.has_prompts)setStepDone(2,'Prompts');
  if(st.has_images)setStepDone(3,st.image_count?`${st.image_count} Imgs`:'Images');
  if(st.has_reviews)setStepDone(4,'Review');
  if(st.has_video)setStepDone(5,'Render');

  if(badge){
   badge.textContent=`Step ${st.current_step}/5`;
   badge.style.color=st.current_step===5?'#9bf5b8':'var(--lime)';
  }

  if(startSelect){
   let defaultStep='beginning';
   if(st.has_video||st.has_reviews){
    defaultStep='render';
   }else if(st.has_images){
    defaultStep='review';
   }else if(st.has_prompts){
    defaultStep='images';
   }else if(st.has_timings){
    defaultStep='prompts';
   }else if(st.has_audio||st.exists){
    defaultStep='timing';
   }

   const chosen=startSelect.querySelector(`option[value="${prevVal}"]`);
   if(chosen&&!chosen.disabled&&(prevVal!=='beginning'||options.live)){
    startSelect.value=prevVal;
   }else{
    startSelect.value=defaultStep;
   }
  }

  if(card&&startSelect){
   const stepMap={1:'timing',2:'prompts',3:'images',4:'review',5:'render'};
   card.querySelectorAll('.pipe-step').forEach(s=>{
    const num=+s.getAttribute('data-step');
    const val=stepMap[num];
    const opt=startSelect.querySelector(`option[value="${val}"]`);
    if(opt&&!opt.disabled){
     s.style.cursor='pointer';
     s.title=opt.textContent;
     s.onclick=()=>{
      startSelect.value=val;
      updateStepHelp();
     };
    }
   });
  }

  if($('audio')){
   $('audio').required=(startSelect&&startSelect.value==='beginning')&&!st.has_audio;
  }
  updateStepHelp();
 }catch(e){
  if(requestVersion!==projectStatusRequestVersion)return;
  if(nameLabel)nameLabel.textContent='Project: '+projId;
  if(badge){badge.textContent='Offline';badge.style.color='var(--warn)';}
 }
}

function updateStepHelp(){
 const sel=$('startStep');
 const help=$('stepHelp');
 if(!sel||!help)return;
 const msgs={
  beginning:'Starts a brand-new project run from scratch without reusing previous data.',
  timing:'Re-runs speech transcription and word timing from audio.',
  prompts:'Reuses existing word timings; regenerates visual scene plan and prompts.',
  images:'Reuses existing word timings and prompts; regenerates illustration images.',
  review:'Reuses existing illustrations and timings; re-runs vision validation.',
  render:'Reuses approved artwork and timings; compiles and renders video MP4.',
  video:'Animates every illustration again with the video model; in-scene lyric spots and the final cut follow.',
  'scene-scan':'Judges every finished clip again for water, land and sky to set lyrics in.'
 };
 help.textContent=msgs[sel.value]||'Choose where to begin execution.';
 window.renderProductionStages?.(state);
 if($('audio')){
  const hasExistingAudio=!!($('projectId')?.value||window.jobId);
  $('audio').required=(sel.value==='beginning')||!hasExistingAudio;
 }
 const card=$('projectPipelineCard');
 if(card){
  const stepMap={'timing':1,'prompts':2,'images':3,'review':4,'render':5};
  const activeNum=stepMap[sel.value];
  card.querySelectorAll('.pipe-step').forEach(s=>{
   const num=+s.getAttribute('data-step');
   if(num===activeNum){
    s.style.outline='2px solid var(--lime)';
   }else{
    s.style.outline='none';
   }
  });
 }
}
if($('startStep'))$('startStep').onchange=()=>{$('startSubstep').value='';updateStepHelp()};
$('startAtStage').onclick=()=>$('jobForm').requestSubmit($('generate'));
new MutationObserver(()=>window.syncStartAtStage?.()).observe($('generate'),{attributes:true,attributeFilter:['disabled']});

window.updateProjectPipelineStatus=updateProjectPipelineStatus;

function saveNamedProfile(name,settings){name=name.trim().slice(0,80);if(!name)throw Error('Enter a profile name first');if(['__proto__','prototype','constructor'].includes(name))throw Error('Choose another profile name');const profiles=getProfiles();profiles[name]={version:1,settings};localStorage.setItem(PROFILE_KEY,JSON.stringify(profiles));localStorage.setItem(ACTIVE_PROFILE_KEY,name);refreshProfiles(name);$('profileName').value=name;renderProductionStages(state);}
$('newProfile').onclick=()=>{$('profileList').value='';$('profileName').value='';$('profileName').focus();$('loadProfile').disabled=true;$('deleteProfile').disabled=true;toast('Enter a profile name and Save to keep the current settings.');};
$('profileList').onchange=()=>{const name=$('profileList').value;$('profileName').value=name;$('loadProfile').disabled=!name;$('deleteProfile').disabled=!name;};
$('saveProfile').onclick=async()=>{try{await persistProfileAudio();saveNamedProfile($('profileName').value,profileSettings());toast('Profile saved.')}catch(e){toast(e.message)}};
$('loadProfile').onclick=()=>loadNamedProfile($('profileList').value);
$('deleteProfile').onclick=()=>deleteNamedProfile($('profileList').value);
async function loadNamedProfile(name){try{const profile=getProfiles()[name];if(!profile)throw Error('Choose a saved profile');await applyProfile(profile.settings);localStorage.setItem(ACTIVE_PROFILE_KEY,name);refreshProfiles(name);$('profileName').value=name;renderProductionStages(state);toast('Profile loaded into the creative brief.')}catch(e){toast(e.message)}}
// Always asks first. The bundled profile comes back on the next start, so it is not offered for deleting.
async function deleteNamedProfile(name){
 if(!name)return;if(name===DEFAULT_PROFILE_NAME){toast('The built-in profile cannot be deleted.');return}
 const yes=await window.studioProjects.ask({title:'Delete this profile?',confirm:'Delete',danger:true,text:`“${name}” and its saved settings are removed from this browser. This cannot be undone.`});
 if(!yes)return;
 try{const profiles=getProfiles();delete profiles[name];if(localStorage.getItem(ACTIVE_PROFILE_KEY)===name)localStorage.removeItem(ACTIVE_PROFILE_KEY);localStorage.setItem(PROFILE_KEY,JSON.stringify(profiles));const kept=$('profileList').value===name?'':$('profileList').value;refreshProfiles(kept);$('profileName').value=kept;syncProfilePicker();renderProductionStages(state);toast('Profile deleted.')}catch(e){toast(e.message)}
}
async function newNamedProfile(){
 const name=await window.studioProjects.ask({title:'New profile',input:true,confirm:'Save'});if(!name)return;
 try{if(Object.hasOwn(getProfiles(),name.slice(0,80)))throw Error(`A profile named “${name}” already exists.`);await persistProfileAudio();saveNamedProfile(name,profileSettings());toast('Profile saved.')}catch(e){toast(e.message)}
}
// The header's profile picker works like the session picker: New Profile first, then every profile with a delete button.
const profilePicker=$('profilePicker'),profileMenu=$('profileMenu'),profileSummary=profilePicker.querySelector('summary');
function syncProfilePicker(){
 let names=[];try{names=Object.keys(getProfiles()).sort()}catch{toast('Profiles could not be read from browser storage.')}
 const active=localStorage.getItem(ACTIVE_PROFILE_KEY)||'';
 const row=(text,choose,current=false)=>{const line=document.createElement('div');line.className='song-row';line.setAttribute('aria-current',String(current));
  const pick=button(text,()=>{profilePicker.open=false;profileSummary.focus();choose()});pick.className='song-choice';line.append(pick);return line};
 profileMenu.replaceChildren(row('New Profile',newNamedProfile),...names.map(name=>{
  const line=row(name,()=>loadNamedProfile(name),name===active);
  if(name!==DEFAULT_PROFILE_NAME){const remove=button('×',()=>deleteNamedProfile(name));remove.className='song-remove';remove.setAttribute('aria-label','Delete profile '+name);remove.title='Delete profile';line.append(remove)}
  return line}));
}
profilePicker.addEventListener('toggle',()=>{if(profilePicker.open)syncProfilePicker()});
profilePicker.addEventListener('keydown',event=>{if(event.key==='Escape'){profilePicker.open=false;profileSummary.focus()}if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const buttons=[...profileMenu.querySelectorAll('button')];const index=buttons.indexOf(document.activeElement);buttons[(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus()}});
document.addEventListener('click',event=>{if(!profilePicker.contains(event.target))profilePicker.open=false});
$('exportProfile').onclick=async()=>{try{await persistProfileAudio();const name=$('profileName').value.trim()||'lyric-studio';const data={version:1,name,settings:profileSettings()};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name.replace(/[^a-z0-9_-]/gi,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message)}};
$('importProfile').onclick=()=>$('profileFile').click();
$('profileFile').onchange=async()=>{try{const file=$('profileFile').files[0];if(!file)return;if(file.size>65536)throw Error('Profile must be smaller than 64 KB');const p=JSON.parse(await file.text());if(p.version!==1||typeof p.name!=='string'||!p.settings||typeof p.settings!=='object')throw Error('Not a supported Kinetic Lyrics profile');await applyProfile(p.settings);saveNamedProfile(p.name,profileSettings());toast('Profile imported and loaded.')}catch(e){toast(e.message)}finally{$('profileFile').value=''}};
function updateDensity(){$('densityValue').value=(+$('particleIntensity').value).toFixed(1)+'×'}
$('particleIntensity').oninput=updateDensity;
function updateSpeed(){if($('particleSpeed')&&$('speedValue'))$('speedValue').value=(+$('particleSpeed').value).toFixed(1)+'×'}
if($('particleSpeed'))$('particleSpeed').oninput=updateSpeed;
init();

function initSpeech(cfg){
    audioModels=cfg.asr_models||[];
    $('asrModel').replaceChildren(...audioModels.map(m=>new Option(m.name,m.id)));
    if(!audioModels.length)$('asrModel').add(new Option('Restart studio to select audio models','qwen3-asr-1.7b'));
    $('asrModel').value=cfg.default_asr||'qwen3-asr-1.7b';
    $('language').replaceChildren(new Option('Auto-detect','auto'),...Object.entries(cfg.vocal_languages||VOCAL_LANGUAGES).sort((a,b)=>a[1].localeCompare(b[1])).map(([code,name])=>new Option(name.replace(/\b\w/g,c=>c.toUpperCase())+' ('+code+')',code)));
    $('asrModel').onchange=speechInfo;$('language').onchange=speechInfo;$('alignmentModel').onchange=speechInfo;
    const previous=$('lyrics').oninput;$('lyrics').oninput=()=>{previous?.();speechInfo()};
    speechInfo();
}
function speechInfo(){
    if(wordAlignmentProtected()){
        $('language').setCustomValidity('');
        $('speechHelp').textContent='Imported timeframe: ASR and word alignment are skipped. Saved word timestamps are used unchanged.';
        $('languageHelp').textContent='The imported lyrics and timeframe are used for this song.';
        return;
    }
    const m=audioModels.find(m=>m.id===$('asrModel').value);if(!m)return;
    const language=$('language').value;const supplied=!!$('lyrics').value.trim();
    const unsupported=language!=='auto'&&!m.languages.includes(language)&&!supplied;
    $('language').setCustomValidity(unsupported?'This audio model does not support the selected language. Choose another model, or supply your lyrics.':'');
    $('speechHelp').textContent=m.description+' '+m.languages.length+' supported languages. '+(supplied?'Supplied lyrics skip transcription; the word timing model is used.':'Missing speech weights download to the model folder under speech/.');
    $('speechLink').href='https://huggingface.co/'+m.repo;
    $('languageHelp').textContent=unsupported?'Choose a different audio model for this language.':'All 100 Whisper languages are listed. Audio models support different subsets.';
}
