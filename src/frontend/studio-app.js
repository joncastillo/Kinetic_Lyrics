// Studio core: API access, the song picker, lyric/audio inputs, uploads and the Generate button state.
// Classic script: its top-level declarations are shared with the modules loaded after it.
const $=id=>document.getElementById(id);let token='',jobId='',cursor=0,logs=[],refs=[],state=null,selected={},gallerySignature='',videoUrl='',busy=false,uploading=false;const stages=['alignment','song','meanings','story','scenes','fit','sections','model','references','reference-check','illustrations','illustration-check','cutouts','review','video','scene-scan','direction','pictures','render'];
renderProductionStages();
$('jobForm').addEventListener('change',()=>{if(!jobId)renderProductionStages()});
// The toast is a popover, shown afresh each time: a modal dialog sits in the top layer, and a plain element (even at
// a high z-index) stayed hidden behind it, so a failed delete in Replace or Verify looked like nothing happened.
function toast(message){const t=$('toast');t.textContent=message;t.style.display='block';
 if(t.showPopover){if(!t.popover){t.popover='manual';Object.assign(t.style,{top:'auto',margin:'0',borderTop:'0',borderRight:'0',borderBottom:'0'})}
  try{if(t.matches(':popover-open'))t.hidePopover();t.showPopover()}catch{}}
 clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>{t.style.display='none';try{t.hidePopover?.()}catch{}},9000)}
async function api(path,data,timeout=45000){
 for(let attempt=0;attempt<2;attempt++){
  const options=data===undefined?{}:{method:'POST',headers:{'X-Studio-Token':token},body:data instanceof FormData?data:JSON.stringify(data)};
  if(data!==undefined&&!(data instanceof FormData))options.headers['Content-Type']='application/json';
  options.signal=AbortSignal.timeout(timeout);
  const r=await fetch(path,options);const body=await r.json();
  if(r.status===403&&body.error==='Reload the studio page'&&data!==undefined&&attempt===0){
   const connection=await fetch('/api/config',{signal:AbortSignal.timeout(15000)});
   const config=await connection.json();if(!connection.ok||!config.token)throw Error('Could not reconnect to Studio');
   token=config.token;continue;
  }
  if(!r.ok)throw Error(body.error||'Request failed');return body;
 }
}
function button(text,callback,disabled=false){const b=document.createElement('button');b.textContent=text;b.type='button';b.disabled=disabled;b.onclick=callback;return b}

const removedSongKey='lyricStudioRemovedSongs';
let removedSongs=new Set();
try{const saved=JSON.parse(localStorage.getItem(removedSongKey)||'[]');if(Array.isArray(saved))removedSongs=new Set(saved)}catch{}
function visibleJobs(jobs){return jobs.filter(j=>!removedSongs.has(j.id))}
// Songs started in another window appear here without a reload; the selection is left alone.
setInterval(async()=>{try{const response=await fetch('/api/job-list',{cache:'no-store'});if(!response.ok)return;const list=visibleJobs((await response.json()).jobs);const known=new Set([...$('jobs').options].map(o=>o.value));const fresh=list.filter(j=>!known.has(j.id));if(!fresh.length)return;for(const j of fresh.reverse())$('jobs').insertBefore(new Option(j.name+' · '+j.id,j.id),$('jobs').options[1]||null);syncSongPicker()}catch{}},10000);
const songPicker=document.createElement('details');songPicker.className='song-picker';
const songSummary=document.createElement('summary');songSummary.setAttribute('aria-label','Previous songs');
const songLabel=document.createElement('span');songLabel.className='song-picker-label';songSummary.append(songLabel);
const songMenu=document.createElement('div');songMenu.className='song-menu';songMenu.setAttribute('role','group');songMenu.setAttribute('aria-label','Previous songs');songPicker.append(songSummary,songMenu);
$('jobs').hidden=true;$('jobs').after(songPicker);
function syncSongPicker(){
 songLabel.textContent=$('jobs').selectedOptions[0]?.textContent||'New session';songMenu.replaceChildren();
 for(const option of $('jobs').options){
  if(removedSongs.has(option.value))continue;
  const row=document.createElement('div');row.className='song-row';row.setAttribute('aria-current',String(option.value===$('jobs').value));
  const choose=button(option.textContent,()=>{$('jobs').value=option.value;$('jobs').dispatchEvent(new Event('change'));songPicker.open=false;songSummary.focus();syncSongPicker()});choose.className='song-choice';row.append(choose);
  if(option.value){const remove=button('×',async()=>{
   if(!await window.studioProjects.ask({title:'Remove this session?',confirm:'Remove',danger:true,text:`“${option.textContent}” leaves the session list and Home, and the studio cannot bring it back. Its files stay in the output folder.`}))return;
   const next=new Set(removedSongs);next.add(option.value);
   try{localStorage.setItem(removedSongKey,JSON.stringify([...next]))}catch{toast('Could not save the song list.');return}
   removedSongs=next;const wasCurrent=$('jobs').value===option.value;option.remove();if(wasCurrent)newSession();syncSongPicker();songMenu.querySelector('button')?.focus();
  });remove.className='song-remove';remove.setAttribute('aria-label','Remove '+option.textContent+' from list');remove.title='Remove from list';row.append(remove)}
  songMenu.append(row);
 }
}
new MutationObserver(syncSongPicker).observe($('jobs'),{childList:true,subtree:true,characterData:true});
songPicker.addEventListener('toggle',()=>{if(songPicker.open)syncSongPicker()});
songPicker.addEventListener('keydown',event=>{if(event.key==='Escape'){songPicker.open=false;songSummary.focus()}if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const buttons=[...songMenu.querySelectorAll('button')];const index=buttons.indexOf(document.activeElement);buttons[(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus()}});
document.addEventListener('click',event=>{if(!songPicker.contains(event.target))songPicker.open=false});
syncSongPicker();

function timeText(seconds){return Math.floor(seconds/60).toString().padStart(2,'0')+':'+Math.floor(seconds%60).toString().padStart(2,'0')}
function splitImages(count,pattern){let images=0,at=0;while(at<count){at+=pattern[images%pattern.length];images++}return images}
function lineCount(){const count=$('lyrics').value.split(/\r?\n/).filter(s=>s.trim()&&!/^\s*\[.*\]\s*$/.test(s)).length;const value=$('lines').value.trim().toLowerCase();const n=+value;$('lineCount').textContent=!count?'Leave blank to recover lyrics and timing with Whisper':value==='auto'?`${count} lyric lines · image grouping chosen by the text model`:Number.isInteger(n)&&n>0?`${count} lyric lines in ${Math.ceil(count/n)} images · each image's lines coloured and numbered above`:/^\d+(-\d+)+$/.test(value)?`${count} lyric lines in ${splitImages(count,value.split('-').map(Number))} images by the pattern ${value} · each image's lines coloured and numbered above`:'Enter Auto, a number from 1 to 50, or a pattern such as 2-3-2-4'}
const lyricsDraftKey='lyricStudioLyricsDraft';
const timingsDraftKey='lyricStudioTimingsDraft';
let songTimings=null;
let savedWordTimingsAvailable=false;
function parseLyricSplit(payload){
 if(!payload||Array.isArray(payload)||!Object.hasOwn(payload,'lyric_split'))return null;
 const split=payload.lyric_split;
 const value=String(typeof split==='object'&&split!==null?split.value:split).trim().toLowerCase();
 const mode=value==='auto'?'auto':/^\d+$/.test(value)?'equal':/^\d+(-\d+)+$/.test(value)?'manual':'';
 if(!mode||value!=='auto'&&value.split('-').some(n=>+n<1||+n>50)||typeof split==='object'&&split?.mode!==mode)throw Error('Invalid lyric split. Use Auto, 1–50, or a pattern such as 2-3-2-4.');
 return {mode,value};
}
function lyricSplitSettings(){return parseLyricSplit({lyric_split:$('lines').value})}
function timelineLyrics(payload,timings){
 const lyrics=typeof payload?.lyrics==='string'&&payload.lyrics.trim()?payload.lyrics:timings.map(line=>line.text).join('\n');
 const lines=lyrics.split(/\r?\n/).map(line=>line.trim()).filter(line=>line&&!/^\[.*\]$/.test(line));
 if(lines.length!==timings.length||lines.some((line,i)=>line!==timings[i].text))throw Error('Annotated lyrics do not match the timing lines.');
 return lyrics;
}
function applyLyricSplit(split,notify=true){
 if(!split)return;
 $('lines').value=split.value;$('linesMode').value=split.mode;
 if(notify){$('lines').dispatchEvent(new Event('input',{bubbles:true}));$('lines').dispatchEvent(new Event('change',{bubbles:true}));lineCount()}
}
function saveTimingsDraft(){
 try{if(songTimings)localStorage.setItem(timingsDraftKey,JSON.stringify({timings:songTimings,lyrics:$('lyrics').value,lyric_split:lyricSplitSettings(),protect_word_alignment:$('protectWordAlignment').checked}));else localStorage.removeItem(timingsDraftKey)}catch{}
}
function wordAlignmentProtected(){return !!(currentSongTimings()||savedWordTimingsAvailable)&&$('protectWordAlignment').checked}
function currentSongTimings(){
 if(!songTimings)return null;
 const lines=$('lyrics').value.split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&!/^\[.*\]$/.test(s));
 return lines.length===songTimings.length&&lines.every((line,i)=>line===songTimings[i].text)?songTimings:null;
}
function setSongTimings(lines,protect=true){
 songTimings=lines||null;
 $('protectWordAlignment').checked=!!songTimings&&protect;
 $('protectWordAlignment').disabled=!songTimings&&!savedWordTimingsAvailable;
 $('lyricTimings').value=songTimings&&protect?JSON.stringify(songTimings):'';
 $('editLyricsTimeline').hidden=!songTimings&&!savedWordTimingsAvailable;
 $('lyricsTimingStatus').textContent=songTimings?'Saved timeframe loaded. ASR and word alignment will be skipped.':'';
 saveTimingsDraft();
 window.dispatchEvent(new Event('song-timings-changed'));
}
function parseSongTimings(parsed){
 const lines=Array.isArray(parsed)?parsed:parsed?.timings;
 if(!Array.isArray(lines)||!lines.length)throw Error('The JSON needs a non-empty timings list.');
 const normalize=text=>text.toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
 let previous=-1;
 return lines.map((line,i)=>{
  if(typeof line?.text!=='string'||!line.text.trim()||/[\r\n]/.test(line.text)||/^\s*\[.*\]\s*$/.test(line.text)||!Array.isArray(line.words)||!line.words.length)throw Error(`Line ${i+1} needs lyric text and word timestamps.`);
  const words=line.words.map(word=>{
   if(typeof word?.text!=='string'||!word.text.trim()||typeof word.start!=='number'||typeof word.end!=='number'||!Number.isFinite(word.start)||!Number.isFinite(word.end)||word.start<0||word.end<=word.start||word.start<previous)throw Error(`Line ${i+1} has invalid word timestamps.`);
   previous=word.start;return {text:word.text,start:word.start,end:word.end};
  });
  if(normalize(words.map(w=>w.text).join(' '))!==normalize(line.text))throw Error(`Line ${i+1} has words that differ from its lyrics.`);
  return {text:line.text.trim(),words};
 });
}
let lyricsStorageWarning=false;
function saveLyricsDraft(){if(songTimings&&!currentSongTimings()){setSongTimings(null);$('lyricsTimingStatus').textContent='Lyrics changed. Import the timeframe again to use saved word timings.'}try{localStorage.setItem(lyricsDraftKey,$('lyrics').value);lyricsStorageWarning=false}catch{if(!lyricsStorageWarning){toast('Lyrics could not be saved in this browser. Copy them before closing the page.');lyricsStorageWarning=true}}}
function isImportedSongMeaning(value){const text=String(value||'').trim();return /^Song meaning \(a non-literal reading of the full lyrics\):/i.test(text)||/^The narrator is\b/i.test(text)&&/\bcentral message\b/i.test(text)}
try{const draft=localStorage.getItem(lyricsDraftKey);if(draft!==null)$('lyrics').value=draft}catch{}
try{const draft=localStorage.getItem(timingsDraftKey);if(draft){const payload=JSON.parse(draft);songTimings=parseSongTimings(payload);applyLyricSplit(parseLyricSplit(payload),false);setSongTimings(currentSongTimings(),payload?.protect_word_alignment!==false)}}catch{setSongTimings(null)}
$('lines').addEventListener('input',saveTimingsDraft);$('lines').addEventListener('change',saveTimingsDraft);
$('protectWordAlignment').onchange=()=>{
 $('lyricTimings').value=wordAlignmentProtected()&&songTimings?JSON.stringify(songTimings):'';
 $('lyricsTimingStatus').textContent=wordAlignmentProtected()?'Word alignment is protected. ASR and word alignment will be skipped; stem separation still runs.':'The model may replace word alignment when generating.';
 saveTimingsDraft();
 speechInfo();
};
$('lyrics').addEventListener('input',saveLyricsDraft);
$('lyrics').addEventListener('input',saveTimingsDraft);
$('lyrics').oninput=lineCount;$('lines').oninput=lineCount;$('loadLyrics').onclick=()=>$('lyricsFile').click();
$('lyricsFile').onchange=async()=>{
 const input=$('lyricsFile'),file=input.files[0];input.value='';if(!file)return;
 try{
  const text=(await file.text()).replace(/^\uFEFF/,'');
  const timings=/\.json$/i.test(file.name)||file.type==='application/json'?parseSongTimings(JSON.parse(text)):null;
  const split=timings?parseLyricSplit(JSON.parse(text)):null;
  const lyrics=timings?timelineLyrics(JSON.parse(text),timings):text;
  $('lyrics').value=lyrics;
  applyLyricSplit(split);
  setSongTimings(timings);saveLyricsDraft();lineCount();speechInfo();
  $('lyrics').dispatchEvent(new Event('input',{bubbles:true}));
 }catch(error){toast('Could not import '+file.name+': '+error.message)}
};
$('editLyricsTimeline').onclick=()=>window.openSongTimeline?.();
$('loadStory')?.addEventListener('click',()=>$('storyFile')?.click());$('storyFile')?.addEventListener('change',async()=>{const f=$('storyFile')?.files?.[0];if(f){$('storyPrompt').value=await f.text();$('storyPrompt').dispatchEvent(new Event('input',{bubbles:true}))}});
let audioObjectUrl='';$('audio').onchange=()=>{audioRestoreVersion++;profileAudioPath='';profileAudioName='';profileAudioFile=null;profileAudioStatus('');if(audioObjectUrl){URL.revokeObjectURL(audioObjectUrl);audioObjectUrl=''}const f=$('audio').files[0];$('audioPreview').hidden=!f;if(f){audioObjectUrl=URL.createObjectURL(f);$('audioPreview').src=audioObjectUrl;persistProfileAudio().catch(e=>{if($('audio').files[0]===f)profileAudioStatus('Audio could not be remembered: '+e.message,true)})}else{$('audioPreview').pause();$('audioPreview').removeAttribute('src');rememberAudioDraft()}};
$('importYoutube').onclick=async()=>{const url=$('youtubeUrl').value.trim();if(!url){toast('Paste one YouTube song link.');return}const button=$('importYoutube');button.disabled=true;$('youtubeImportStatus').textContent='Downloading audio and comparing lyrics sources…';try{const result=await api('/api/import-youtube',{url},300000);await restoreProfileAudio({audio_path:result.audio_path,audio_name:result.audio_name});if(!$('audio').files.length)throw Error('Downloaded audio could not be loaded into the form');$('lyrics').value=typeof result.lyrics==='string'?result.lyrics:'';saveLyricsDraft();lineCount();speechInfo();$('youtubeImportStatus').textContent=result.lyrics_source?`Imported ${result.track.title} · lyrics from ${result.lyrics_source} (${result.candidates.length} candidates compared)`:`Imported ${result.track.title} · no lyric match; transcription will run`;if(result.lyrics_source)toast('YouTube audio and '+result.lyrics_source+' lyrics are ready.')}catch(error){$('youtubeImportStatus').textContent='Import failed: '+error.message;toast(error.message)}finally{button.disabled=false}};
function showRefs(){$('refList').replaceChildren();(window.savedReferences||[]).forEach((url,index)=>{const div=document.createElement('div');div.className='ref saved';div.title='Saved with this project: the image model read it when the artwork was made. Add new pictures beside it; they are uploaded on the next generation.';const img=document.createElement('img');img.src=url;img.alt='Project reference';div.append(img,tagCaption('@photo'+(index+1)));if(jobId)div.append(button('×',async()=>{try{const result=await api(`/api/jobs/${jobId}/reference-remove`,{url});window.savedReferences=result.references||[];showRefs()}catch(e){toast('Could not remove the reference: '+e.message)}}));$('refList').append(div)});refs.forEach((ref,i)=>{const div=document.createElement('div');div.className='ref';const img=document.createElement('img');img.src=ref.url;img.alt=ref.file.name;div.append(img,button('×',()=>{URL.revokeObjectURL(ref.url);refs.splice(i,1);showRefs()}));$('refList').append(div)})}
$('references').onchange=()=>{for(const file of $('references').files)refs.push({file,url:URL.createObjectURL(file)});$('references').value='';showRefs();warnReferences(true)};
// Not every image model reads reference pictures. Say so beside the pictures (and once as a toast when adding them),
// naming the models that do; casting the main character still uses them, as words, with any model.
function imageModelTakesReferences(id=$('imageModel')?.value){const spec=(window.imageModels||imageModels||[]).find(m=>m.id===id);return spec?spec.references!==false:true}
function warnReferences(adding=false){
 const note=$('refWarning');if(!note)return;
 const count=refs.length+(window.savedReferences||[]).length;
 const model=$('imageModel')?.selectedOptions[0]?.textContent||'This image model';
 const able=(imageModels||[]).filter(m=>m.references).map(m=>m.name).join(', ');
 const show=count>0&&!imageModelTakesReferences();
 note.hidden=!show;
 if(show){note.textContent=`${model} does not read reference images, so the artwork ignores them`+($('castReference')?.checked?' (the main character is still described from them in words)':'')+`. To use them, choose ${able||'an image model that takes references'}.`;
  if(adding)toast(note.textContent)}
}
document.addEventListener('change',event=>{if(['imageModel','castReference'].includes(event.target?.id))warnReferences()});
// The Replace or verify dialog shows the project's references; adding or removing one changes the project, so the
// replacement (and every later generation) uses them.
// The tag that names a reference picture in a scene prompt (see direction.entities.reference_tags): a name with its
// spaces as underscores, quoted when it holds other characters.
function referenceTag(name){const text=String(name||'').trim().split(/[\\/]/).pop();if(!text)return '';  /* a file's name, never its folders */if(/\.(png|jpe?g|webp)$/i.test(text))return '@'+text.replace(/\s+/g,'_');const plain=text.replace(/[^\w\s-]+/g,'').trim().replace(/\s+/g,'_');return plain?'@'+plain:'@"'+text+'"'}
async function copyText(text,near){try{await navigator.clipboard.writeText(text)}catch{  // no clipboard API on plain http away from localhost
 const box=document.createElement('textarea');box.value=text;box.style.cssText='position:fixed;opacity:0';near.append(box);box.select();const copied=document.execCommand('copy');box.remove();if(!copied)throw Error('no clipboard')}}
// The tag says it was copied itself: a toast would sit behind the Replace dialog.
function tagCaption(tag){const small=document.createElement('small');small.className='ref-tag';small.dataset.tag=tag;small.textContent=tag;small.title=tag+' · click to copy, then paste it in the scene prompt';
 small.onclick=async event=>{event.preventDefault();event.stopPropagation();let word='Copied';try{await copyText(tag,small.parentNode)}catch{word='Could not copy'}
  small.textContent=word;clearTimeout(small.restore);small.restore=setTimeout(()=>small.textContent=tag,1200)};return small}
window.referenceTag=referenceTag;window.tagCaption=tagCaption;
function renderRegenerateRefs(){
 const strip=$('regenerateRefs');if(!strip)return;strip.replaceChildren();
 (window.savedReferences||[]).forEach((url,i)=>{
  const div=document.createElement('div');div.className='ref saved';const img=document.createElement('img');img.src=url;img.alt='Project reference';
  div.append(img,button('×',async()=>{try{const r=await api(`/api/jobs/${jobId}/reference-remove`,{url});window.savedReferences=r.references||[];showRefs();renderRegenerateRefs()}catch(e){toast('Could not remove the reference: '+e.message)}}),tagCaption('@photo'+(i+1)));
  strip.append(div);
 });
 if(!(window.savedReferences||[]).length)strip.append(Object.assign(document.createElement('span'),{className:'help',textContent:'No reference images.'}));
 const note=$('regenerateRefWarning');
 if(note){const show=(window.savedReferences||[]).length>0&&!imageModelTakesReferences();note.hidden=!show;
  note.textContent=show?`${$('imageModel')?.selectedOptions[0]?.textContent||'This image model'} does not read reference images, so a replacement ignores them.`:''}
}
$('regenerateRefFile')?.addEventListener('change',async event=>{
 const files=[...event.target.files];event.target.value='';if(!files.length||!jobId)return;
 const form=new FormData();files.forEach(f=>form.append('reference',f));
 try{const r=await api(`/api/jobs/${jobId}/reference-add`,form);window.savedReferences=r.references||[];showRefs();renderRegenerateRefs()}
 catch(e){toast('Could not add the reference: '+e.message)}
});
if($('regenerateModal'))new MutationObserver(()=>{if($('regenerateModal').open)renderRegenerateRefs()}).observe($('regenerateModal'),{attributes:true,attributeFilter:['open']});
function updateGenerate(){const reason=!backendReady?'Connecting to the studio backend. Refresh after a server restart.':!imageInstructionsSupported&&$('imageInstructions').value.trim()?'Restart Kinetic Lyrics to apply the image prompt instructions. The running backend cannot receive this field.':uploading?'Uploading your inputs...':state?.action?'Wait for the current image operation to finish.':['running','queued'].includes(state?.status)?'This job is still running.':state?.status==='review'?'Artwork is ready for review. Use Approve artwork & render, or choose New session to start another video.':'';$('generate').disabled=!!reason;$('generate').title=reason;$('generateReason').textContent=reason;$('regenerateSessionButton').disabled=!sessionRegenerationSupported||!jobId||uploading||!!state?.action||['running','queued','review'].includes(state?.status);$('regenerateSessionButton').title=!sessionRegenerationSupported?'Restart the studio backend to enable this action.':'Run every step again with this session’s inputs in a fresh session.';}
$('imageInstructions').addEventListener('input',updateGenerate);
function newSession(){savedWordTimingsAvailable=false;if(!songTimings)setSongTimings(null);window.savedReferences=[];if($('projectName'))$('projectName').value='';if($('randomizeSeed'))$('randomizeSeed').checked=true;if($('imageSeed')){$('imageSeed').value='';$('imageSeed').placeholder='Random per image';}jobId=null;cursor=0;state=null;logs=[];selected={};gallerySignature='';typographySignature='';$('smallImagePanel').hidden=true;videoUrl='';localStorage.removeItem('lyricStudioJob');document.body.classList.remove('has-job');$('jobs').value='';if($('projectId'))$('projectId').value='';if(window.updateProjectPipelineStatus)updateProjectPipelineStatus('');syncSongPicker();$('video').pause();$('video').removeAttribute('src');$('videoPanel').style.display='none';$('rebuildPanel').hidden=true;$('rebuildDock').hidden=true;$('reviewBanner').style.display='none';$('gallery').innerHTML='<div class="empty">Choose your audio and creative settings to start a new video.</div>';$('logs').replaceChildren();$('status').textContent='Ready';$('message').textContent='Ready for a new video.';$('percent').textContent='0';$('actionProgress').textContent='';$('cancel').disabled=true;$('verifyAll').disabled=true;renderProductionStages();renderProductionHeader(null);updateGenerate();}
$('newSessionButton').onclick=newSession;
$('regenerateSessionButton').onclick=async()=>{if(!jobId||uploading)return;const source=jobId;uploading=true;updateGenerate();try{await ensureSelectedDownloads();const job=await api(`/api/jobs/${source}/regenerate-new`,{image_model:$('imageModel').value});$('jobs').add(new Option('Regenerated · '+job.id,job.id),1);setJob(job.id)}catch(e){toast('Could not regenerate in a new session: '+e.message)}finally{uploading=false;updateGenerate()}};
$('retryConnection').onclick=async()=>{const b=$('retryConnection');b.disabled=true;try{const cfg=await api('/api/config');token=cfg.token;backendReady=!!cfg.image_models;imageInstructionsSupported=!!cfg.image_instructions_supported;sessionRegenerationSupported=!!cfg.new_session_regeneration_supported;const current=jobId;$('jobs').replaceChildren(new Option('New session',''),...visibleJobs(cfg.jobs).map(j=>new Option(j.name+' / '+j.id,j.id)));if(current&&visibleJobs(cfg.jobs).some(j=>j.id===current)){$('jobs').value=current;await poll()}else newSession();updateGenerate();if(profileAudioPath&&!profileAudioFile)restoreProfileAudio({audio_path:profileAudioPath,audio_name:profileAudioName}).catch(()=>{});toast('Connected to the studio.')}catch(e){toast('Could not reconnect: '+e.message)}finally{b.disabled=false}};
function setJob(id){savedWordTimingsAvailable=false;setSongTimings(null);renderSettingsJob=null;typographyFallbackJob='';typographyFallback=[];typographyFallbackTime=0;document.body.classList.add('has-job');jobId=id;cursor=0;logs=[];selected={};state=null;gallerySignature='';typographySignature='';videoUrl='';$('logs').replaceChildren();$('videoPanel').style.display='none';$('gallery').innerHTML='<div class="empty">Loading job…</div>';$('jobs').value=id;if($('projectId'))$('projectId').value=id;if(window.updateProjectPipelineStatus)updateProjectPipelineStatus(id);syncSongPicker();localStorage.setItem('lyricStudioJob',id);poll()}
async function upload(data){try{return await uploadOnce(data)}catch(e){if(e.status!==403)throw e;const config=await (await fetch('/api/config',{signal:AbortSignal.timeout(15000)})).json();if(!config.token)throw Error('Could not reconnect to Studio');token=config.token;return uploadOnce(data)}}
function uploadOnce(data){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/jobs');xhr.timeout=300000;xhr.ontimeout=()=>reject(Error('Upload timed out. Reconnect to check whether a job was created before retrying.'));xhr.setRequestHeader('X-Studio-Token',token);xhr.upload.onprogress=e=>{$('uploadProgress').textContent=e.lengthComputable?`Uploading inputs · ${Math.round(e.loaded/e.total*100)}%`:'Uploading inputs…'};xhr.onload=()=>{try{const r=JSON.parse(xhr.responseText);xhr.status<300?resolve(r):reject(Object.assign(Error(r.error),{status:xhr.status}))}catch{reject(Error('Invalid server response'))}};xhr.onerror=()=>reject(Error('Could not connect to local studio'));xhr.send(data)})}
$('jobForm').onsubmit=async event=>{event.preventDefault();if(uploading)return;
 if(window.commitSongTimeline&&!await window.commitSongTimeline()){toast('Save or correct the imported timeframe before generating.');return}
 if(songTimings&&!currentSongTimings())setSongTimings(null);
 if(wordAlignmentProtected()){
  try{const config=await api('/api/config');if(!config.protected_timings_supported){toast('Restart Kinetic Lyrics before generating: the running backend cannot protect imported word alignment.');return}}
  catch(error){toast(error.message);return}
 }
 if(currentSongTimings()){$('lyricTimings').value=wordAlignmentProtected()?JSON.stringify(songTimings):'';if(!wordAlignmentProtected()&&$('startStep'))$('startStep').value='timing'}
 // AI video: Resume (green) animates only the missing clips; Regenerate (red) remakes every clip
 const own={video:window.resumeStart?'animate-missing':'reanimate-all','scene-scan':'scene-scan'}[$('startStep')?.value];
 if(own&&jobId&&!currentSongTimings()){try{const r=await api(`/api/jobs/${jobId}/${own}`,{});toast(r.message||'Queued.')}catch(e){toast(e.message||String(e))}return}
 uploading=true;if(!window.resumeStart&&['beginning','timing','prompts','images'].includes($('startStep')?.value||'beginning')){$('gallery').innerHTML='<div class="empty">Clearing the previous illustrations. New ones appear here as they are generated.</div>';gallerySignature='';}$('generate').disabled=true;$('uploadProgress').style.display='block';try{if(currentSongTimings())await window.prepareSongWaveforms?.();await ensureSelectedDownloads();const data=new FormData($('jobForm'));data.set('auto_repair',$('autoRepair').checked?'on':'off');data.set('review_references',$('reviewReferences')?.checked===false?'off':'on');data.set('repaint_references',$('repaintReferences')?.checked===false?'off':'on');for(const id of ['imageCheckPrompt','referenceCheckPrompt'])if(window.checkPromptValue)data.set($(id).name,window.checkPromptValue(id));data.set('profile_name',localStorage.getItem(ACTIVE_PROFILE_KEY)||'');refs.forEach(r=>data.append('references',r.file));if(window.resumeStart)data.append('resume','1');data.set('vision_model',$('visionModel').value);data.set('randomize_seed',$('randomizeSeed')?.checked?'on':'off');data.set('image_seed',$('randomizeSeed')?.checked?'':($('imageSeed')?.value.trim()||''));const job=await upload(data);// the pictures just uploaded are the project's own now: they come back as saved references, not twice
refs.forEach(r=>URL.revokeObjectURL(r.url));refs.length=0;showRefs();const songName=$('audio').files[0]?.name||$('jobs')?.selectedOptions[0]?.textContent||job.id;if(![...$('jobs').options].some(o=>o.value===job.id))$('jobs').add(new Option(songName,job.id),1);setJob(job.id)}catch(e){toast(e.message)}finally{uploading=false;$('uploadProgress').style.display='none';updateGenerate()}};
async function action(op,args={}){
 if(!jobId)return;
 const generation=['regenerate','reprompt'].includes(op);
 if(generation)args={...args,image_model:$('imageModel').value,steps:Number($('steps').value)||undefined};
 const queues=generation||op==='verify';  // these wait their turn, so nothing has to be tried again
 if(busy&&!queues){toast('Another action is being submitted. Try again shortly.');return;}
 const expected=jobId;let optimisticKey=null;
 if(generation){
  optimisticKey=expected+':'+args.index+':'+op;
  if(optimisticRegenerations.has(optimisticKey)){toast('This illustration is already being queued.');return;}
  optimisticRegenerations.set(optimisticKey,{job:expected,index:args.index,action:op,accepted:false});
  paintOptimisticQueue();
 }else if(!queues)busy=true;
 try{
  await api(`/api/jobs/${expected}/${op}`,args,op==='replace'?600000:undefined);
  if(op==='cancel')for(const [key,item] of optimisticRegenerations)if(item.job===expected)optimisticRegenerations.delete(key);
  if(optimisticKey&&optimisticRegenerations.has(optimisticKey))optimisticRegenerations.get(optimisticKey).accepted=true;
  recordRebuildAction(op,args);gallerySignature='';if(jobId===expected)await poll();
 }catch(e){
  if(optimisticKey){optimisticRegenerations.delete(optimisticKey);paintOptimisticQueue();}
  toast('Could not '+(generation?'queue illustration '+(Number(args.index)+1):op)+': '+e.message);
 }finally{if(!queues)busy=false;}
}
$('cancel').onclick=()=>action('cancel');$('approve').onclick=()=>action('approve');$('jobs').onchange=()=>{if($('jobs').value)setJob($('jobs').value);else newSession()};
$('refreshModels').onclick=async()=>{const b=$('refreshModels');b.disabled=true;b.textContent='Finding…';try{installModelChoices(await api('/api/models?review='+($('autoVerify').checked?'1':'0')))}catch(e){toast('Model lookup unavailable: '+e.message)}finally{b.disabled=false;b.textContent='Find models'}};
$('rebuildImages').onclick=()=>action('rebuild');function renderSettingsPayload(){return {type_effect:$('typeEffect').value,text_animation:$('textAnimation').value,audio_mode:$('audioMode').value,lettering_styles:$('letteringStyles')?.value,reading_flow:$('readingFlow')?.value,instructions:$('instructions')?.value||'',stage_pictures:$('stagePictures')?.value,depth_model:$('depthModel')?.value,kinetic:$('kinetic')?.value,effect_speeds:$('effectSpeeds')?.value,effect_intensities:$('effectIntensities')?.value,text_pool:selectedParticlePool('text'),font_family:$('fontFamily').value,font_style:$('fontStyle').value,font_scale:+$('fontScale').value,entrance_effect:$('entranceEffect').value,exit_effect:$('exitEffect').value,entrance_pool:selectedParticlePool('entrance'),exit_pool:selectedParticlePool('exit'),particle_intensity:+$('particleIntensity').value,particle_speed:+$('particleSpeed').value}}
$('rebuildEffects').onclick=()=>action('rerender',renderSettingsPayload());
// Every setting in the Project panel is saved into the open project as it changes (a moment after the last edit),
// so switching songs or closing the window keeps them. Only after this project's own settings were restored: before
// that the form still shows the previous project's.
let projectSaveTimer=0,projectSaveFailed=false;
function saveProjectSettings(){
 clearTimeout(projectSaveTimer);
 if(!jobId||renderSettingsJob!==jobId)return;
 const job=jobId;
 projectSaveTimer=setTimeout(async()=>{
  if(job!==jobId||renderSettingsJob!==jobId)return;
  const payload=Object.assign(renderSettingsPayload(),{story_prompt:$('storyPrompt')?.value||'',image_instructions:$('imageInstructions')?.value||'',theme:$('style')?.value||'',style_prompt:$('referencePrompt')?.value||'',image_model:$('imageModel').value,scene_direction:$('sceneDirection')?.value||'timed',video_upscale:$('videoUpscale')?.value||'off',picture_kinds:$('pictureKinds')?.value||'',end_frame_model:$('endFrameModel')?.value||'auto',end_frame_review:!!$('endFrameReview')?.checked,review_references:!!$('reviewReferences')?.checked,repaint_references:!!$('repaintReferences')?.checked,image_check_prompt:window.checkPromptValue?.('imageCheckPrompt')??'',reference_check_prompt:window.checkPromptValue?.('referenceCheckPrompt')??''});
  try{await api(`/api/jobs/${job}/settings`,payload);projectSaveFailed=false}
  catch(e){if(!projectSaveFailed)toast('Project settings could not be saved: '+(e.message||e));projectSaveFailed=true}
 },800);
}
['change','input'].forEach(type=>document.addEventListener(type,event=>{if(event.target?.closest?.('#jobForm, [form="jobForm"]'))saveProjectSettings()}));
$('verifyAll').onclick=()=>action('verify-all',{model:$('visionModel').value,review_threshold:+$('reviewThreshold').value,auto_repair:$('autoRepair').checked});
$('visionModel').onchange=()=>{preferredVisionModel=$('visionModel').value;gallerySignature='';if(state)renderGallery(state)};
// Clicking any reference picture (the project's, newly added ones, or a storyline segment's) shows it zoomed in.
document.addEventListener('click',event=>{
 const img=event.target.closest?.('.ref img, .story-ref img, .story-refs img, .artwork-ref img, img.story-entity-pic');
 if(!img||!$('imageModal'))return;
 event.preventDefault();
 zoomPicture(img.currentSrc||img.src,'Reference image'+(img.alt&&img.alt!=='Project reference'?' · '+img.alt:''));
 showEarlierReferences(img.dataset.entity?(window.referenceEarlier||{})[img.dataset.entity]:null,img.currentSrc||img.src);
});
// A recurring reference's earlier pictures (kept on disk when it was painted again after a failed check or on
// request), to look at under the enlarged one. Clicking one shows it large; none can be put back in use.
function showEarlierReferences(record,shown){
 const strip=$('modalEarlier');if(!strip)return;strip.replaceChildren();
 if(!record||(!record.earlier?.length&&!record.history?.length)){strip.hidden=true;return}
 const note=document.createElement('p');note.className='help';
 note.textContent=`Earlier pictures of ${record.name}, each replaced after a failed check or a repaint · to look at only; the one in use stays in use.`;
 strip.append(note);
 const pictures=[...(record.current?[[record.current,'In use']]:[]),...record.earlier.map((url,i)=>[url,'Earlier '+(i+1)])];
 for(const [url,label] of pictures){
  const fig=document.createElement('figure');const thumb=document.createElement('img');thumb.src=url;thumb.alt=label+' · '+record.name;thumb.loading='lazy';
  if(url===shown)thumb.classList.add('shown');
  thumb.onclick=()=>{$('modalImage').src=url;strip.querySelectorAll('img').forEach(i=>i.classList.toggle('shown',i===thumb));$('modalTitle').textContent='Reference image · '+record.name+(label==='In use'?'':' · '+label.toLowerCase()+', not in use')};
  const review=record.history?.find(item=>item.url===url)?.review;
  const reason=review ? (review.passed?'Passed checker':'Failed checker')+' · '+[review.summary,...(review.issues||[])].filter(Boolean).join('; ') : 'No checker result was saved for this earlier image.';
  const cap=document.createElement('figcaption');cap.textContent=label;
  const detail=document.createElement('p');detail.className='help';detail.textContent=reason;
  fig.append(thumb,cap,detail);strip.append(fig)}
 strip.hidden=false;
}
