// Artwork workspace: the production log, illustration cards, the inspect and replace-or-verify dialogs
// and the small typography pictures.
function renderLogs(){const filter=$('logFilter').value;const el=$('logs');const shown=logs.filter(l=>filter==='all'||filter==='warning'&&l.level!=='info'||filter==='error'&&l.level==='error');el.replaceChildren();for(const l of shown){const row=document.createElement('div');row.className='log-line '+l.level;const t=document.createElement('time');t.textContent=new Date(l.time*1000).toLocaleTimeString([],{hour12:false});const text=document.createElement('span');text.textContent=l.text;row.append(t,text);el.append(row)}if($('autoScroll').checked)el.scrollTop=el.scrollHeight}
$('logFilter').onchange=renderLogs;
// Clear: the log and the progress history (the coloured chart in the header) are emptied on the server; new lines
// and points start from here. The poll cursor restarts so lines written after this are not skipped.
$('clearLog').onclick=async()=>{if(!jobId){toast('No job open.');return}try{await api(`/api/jobs/${jobId}/clear-log`,{});logs=[];cursor=0;renderLogs();const host=$('progressLogs');if(host)host.dataset.count='';if(state){state.logs=[];state.history=[];state.cursor=0;update(state);cursor=0}toast('Log cleared.')}catch(e){toast(e.message||String(e))}};
$('downloadLog').onclick=()=>{const blob=new Blob([logs.map(l=>new Date(l.time*1000).toISOString()+' ['+l.level+'] '+l.text).join('\n')],{type:'text/plain'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='lyric-studio.log';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
function inspect(url,index,clip){const earlier=$('modalEarlier');if(earlier){earlier.hidden=true;earlier.replaceChildren()}const img=$('modalImage');let video=document.getElementById('modalVideo');if(!video){video=document.createElement('video');video.id='modalVideo';video.muted=true;video.loop=true;video.playsInline=true;video.preload='auto';video.className='modal-video';video.onmouseenter=()=>{video.currentTime=0;video.play().catch(()=>{})};video.onmouseleave=()=>{video.pause();};img.after(video)}if(!video.parentElement.classList.contains('inspect-stage')&&img.parentElement.classList.contains('inspect-stage'))img.after(video);if(clip){video.poster=url;if(video.getAttribute('src')!==clip)video.src=clip;video.hidden=false;img.hidden=true}else{video.pause();video.removeAttribute('src');video.hidden=true;img.hidden=false;img.src=url}$('modalTitle').textContent=`Illustration ${index+1} · `+(clip?'hover to play the clip':'inspect anatomy and detail');$('imageModal').showModal()};$('closeModal').onclick=()=>$('imageModal').close();
// A still picture in the shared zoom dialog. Through inspect, so a clip left there by the gallery is hidden, not shown instead.
function zoomPicture(url,title){window.inspect(url,0,null);$('modalTitle').textContent=title}
let regenerateIndex=null,promptRegenerationSupported=false;const pendingSelections={};
// The art style is shown in its own field. Prompts fitted to an image model open with STYLE_LEAD; older prompts carry
// the style inline, so it is cut out there and placed first again only if either field is edited.
const STYLE_LEAD='Art style, the top priority for how everything is rendered: ';
const flatStyle=s=>String(s||'').split(/\s+/).filter(Boolean).join(' ').replace(/\.+$/,'');
function splitStyle(prompt,style){
 prompt=String(prompt||'');const st=flatStyle(style);
 if(st){
  const head=STYLE_LEAD+st+'. ';
  if(prompt.startsWith(head)||prompt===STYLE_LEAD+st+'.')return{scene:prompt.slice(head.length),style:st};
  const pattern=st.replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/ /g,'\\s+');
  const inline=new RegExp('(?:Rendering technique: |Use the following only for color, brushwork and mood, never to replace the scene: )?'+pattern+'\\.?(?:\\s+|$)','g');
  if(inline.test(prompt))return{scene:prompt.replace(inline,'').trim(),style:st};
 }
 if(prompt.startsWith(STYLE_LEAD)){const end=prompt.indexOf('. ',STYLE_LEAD.length);if(end>0)return{scene:prompt.slice(end+2),style:prompt.slice(STYLE_LEAD.length,end)}}
 return{scene:prompt,style:st,missing:!!st};
}
// A prompt written from the storyline carries the labels below, and each gets its own field. Anything else is all
// Scene. Text ahead of the first label goes to Environment, so nothing is lost.
const SECTION_LABELS=[['environment','Environment'],['characters','Characters'],['scene','Scene']];
function splitSections(text){
 text=String(text||'');const pieces=text.split(/\b(Environment|Characters|Scene):\s*/);
 if(pieces.length<3)return{environment:'',characters:'',scene:text,labelled:false};
 const out={environment:pieces[0].trim(),characters:'',scene:'',labelled:true};
 for(let i=1;i<pieces.length;i+=2){const key=pieces[i].toLowerCase();out[key]=[out[key],pieces[i+1].trim()].filter(Boolean).join(' ')}
 return out;
}
function joinSections(sections){
 const filled=SECTION_LABELS.filter(([key])=>sections[key].trim());
 if(filled.length===1&&filled[0][0]==='scene')return sections.scene.trim();
 return filled.map(([key,label])=>label+': '+sections[key].trim()).join('\n');
}
// The dialog opens the illustration's prompt for the selected picture, and for any picture whose own prompt predates
// the labelled fields; other pictures open the exact prompt they were painted from.
const promptSource=(item,picture)=>!picture||picture.current||(splitSections(item.prompt).labelled&&!splitSections(picture.prompt).labelled)?item:picture;
let regenerateOriginal={prompt:'',environment:'',characters:'',scene:'',style:''};
function fillRegeneration(prompt,style){
 const parts=splitStyle(prompt,style),sections=splitSections(parts.scene);
 regenerateOriginal={prompt:String(prompt||''),environment:sections.environment,characters:sections.characters,scene:sections.scene,style:parts.style};
 $('regenerateEnvironment').value=sections.environment;$('regenerateCharacters').value=sections.characters;
 $('regeneratePrompt').value=sections.scene;$('regenerateStyle').value=parts.style;
 $('regenerateSubject').hidden=sections.labelled;  // the fields below say it all
 $('regenerateStyleHelp').textContent=parts.missing?'This prompt did not contain the session art style, so it is shown here and will be placed first if you keep it. Clear the field to generate without it. Changes apply to this image only.':'Starts with the original prompt, split into its art style, environment, characters and scene. Edit any of them; the style is placed first when the new candidate is generated. Changes apply to this image only, and your current selection is kept.';
}
function regenerationPrompt(){
 const sections={environment:$('regenerateEnvironment').value,characters:$('regenerateCharacters').value,scene:$('regeneratePrompt').value},style=$('regenerateStyle').value;
 const same=SECTION_LABELS.every(([key])=>sections[key]===regenerateOriginal[key]);
 if(same&&style===regenerateOriginal.style&&!splitStyle(regenerateOriginal.prompt,style).missing)return regenerateOriginal.prompt;
 const st=flatStyle(style);return (st?STYLE_LEAD+st+'. ':'')+joinSections(sections);
}
let regenerateContext={};
function openRegeneration(index,subject,prompt,variant,style,context={}){regenerateIndex=index;regenerateContext={...context,path:variant?.path};
 const verify=$('verifyRegenerate'),replace=$('submitRegenerate');
 verify.textContent=(context.busy?'Queue ':'')+'Verify 5x';verify.disabled=!!context.verifyReason;verify.title=context.verifyReason||'';
 $('regeneratePromptAction').textContent=context.busy?'Queue new prompt':'Regenerate prompt';replace.textContent=context.busy?'Queue replace':'Replace';replace.disabled=context.canReplace===false;
 $('verifyHelp').textContent=context.verifyReason||('Verify 5x makes a new image from this prompt and style, then checks it with the vision model, up to 5 times; the first that passes is selected'+(context.video?' and its video section is rebuilt.':'.')+' Replace makes one new candidate from the prompt exactly as written.');$('regenerateSubject').textContent=subject;fillRegeneration(prompt,variant?.style||style);$('regenerateDirection').value='';$('regeneratePromptAction').disabled=!promptRegenerationSupported;$('repromptHelp').textContent=promptRegenerationSupported?'Regenerate prompt writes a new interpretation of the lyrics (using the guidance above) and then a new image.':'Restart Kinetic Lyrics after the current task finishes to enable queued prompt regeneration. Replace is available now.';renderRegenerateEntities();$('regenerateModal').showModal();$('regeneratePrompt').focus();restoreExactCandidatePrompt(variant,index,$('regeneratePrompt').value)}
async function restoreExactCandidatePrompt(variant,index,initial){
 if(!variant||typeof variant.prompt==='string'||!variant.url)return;
 const url=new URL(variant.url,location.href),root=url.pathname.match(/^\/files\/[^/]+\//)?.[0];
 if(!root)return;
 try{
  let relative=variant.path;
  if(variant.current){
   const response=await fetch(url.pathname.replace(/\.png$/,'.selection.json'));
   if(!response.ok)return;
   const selection=await response.json(),saved=String(selection.selected||'').split(String.fromCharCode(92)).join('/');
   const position=saved.lastIndexOf('/candidates/');if(position<0)return;
   relative=saved.slice(position+1);
  }
  let record,position=0;
  if(/^candidates\/\d{3}\/[^/]+\/\d{3}\.png$/.test(relative)){
   const response=await fetch(root+relative.replace(/[^/]+$/,'illustrations.json'));if(!response.ok)throw Error('Candidate prompt could not be loaded');
   record=await response.json();
  }else if(/^versions\//.test(relative)){
   const response=await fetch(root+relative.replace(/\.png$/,'.artwork.json'));if(!response.ok)return;
   const metadata=await response.json();record={prompts:[metadata.prompt],visual_descriptions:[metadata.subject],style_prompt:metadata.style};
  }else return;
  if(regenerateIndex!==index||!$('regenerateModal').open||$('regeneratePrompt').value!==initial)return;
  if(typeof record.prompts?.[position]==='string')fillRegeneration(record.prompts[position],record.style_prompt||$('regenerateStyle').value);
  if(typeof record.visual_descriptions?.[position]==='string')$('regenerateSubject').textContent=record.visual_descriptions[position];
 }catch(e){if(regenerateIndex===index&&$('regenerateModal').open)$('repromptHelp').textContent=e.message+'. Check the prompt before generating.'}
}
$('closeRegenerate').onclick=()=>$('regenerateModal').close();
$('verifyRegenerate').onclick=()=>{const prompt=regenerationPrompt();$('regenerateModal').close();
 action('verify',{index:regenerateIndex,path:regenerateContext.path,model:$('visionModel').value,review_threshold:+$('reviewThreshold').value,auto_repair:true,
  prompt,style:flatStyle($('regenerateStyle').value)})};
$('regeneratePromptAction').onclick=()=>{const prompt=[$('imageInstructions').value,$('regenerateDirection').value].filter(Boolean).join('\n');$('regenerateModal').close();action('reprompt',{index:regenerateIndex,prompt,model:$('aiModel').value,style:flatStyle($('regenerateStyle').value)})};
$('submitRegenerate').onclick=()=>{const prompt=regenerationPrompt();$('regenerateModal').close();action('regenerate',{index:regenerateIndex,prompt,style:flatStyle($('regenerateStyle').value)})};

function renderGallery(s){const stoppedVideo=['cancelled','failed'].includes(s.status)&&!!s.video&&!s.action;const stoppedReview=s.status==='cancelled'&&s.stage==='review'&&!s.action;  /* stopped at the review pause: its pictures are finished */const editable=(['review','complete'].includes(s.status)||stoppedVideo||stoppedReview||['running','queued'].includes(s.status))&&(!s.action||['verify','regenerate','reprompt','repair','reference','animate','clip-effects','scene-scan'].includes(s.action));const canRegenerate=['running','review','complete'].includes(s.status)||stoppedVideo;const sig=JSON.stringify([s.images,s.status,s.stage,s.action,s.dirty,s.queued_actions,s.artwork_notice,s.entity_references,$('visionModel').value]);if(sig===gallerySignature)return;gallerySignature=sig;const gallery=$('gallery');const previousImages=new Map([...gallery.querySelectorAll('[data-image-index]')].map(card=>[+card.dataset.imageIndex,card.querySelector('.image-stage video')||card.querySelector('.image-stage img')]));gallery.replaceChildren();if(s.artwork_notice){const note=document.createElement('p');note.className='workspace-notice';note.textContent=s.artwork_notice;gallery.append(note)}if(!s.images.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='Planning illustrations. Finished images will appear here automatically.';gallery.append(empty);return}for(const item of s.images){const card=document.createElement('article');card.className='image-card';card.dataset.imageIndex=item.index;const variants=item.variants;const queued=(s.queued_actions||[]).find(q=>q.index===item.index&&['regenerate','reprompt'].includes(q.action||'regenerate'));const pending=(item.pending==='Image queued'?'Queued for regeneration':item.pending)||(queued?(queued.action==='reprompt'?'Prompt queued':'Queued for regeneration'):'');const latest=variants.filter(v=>v.path.startsWith('candidates/')).at(-1);if((s.replacement_review||[]).includes(item.index)&&latest?.review&&!latest.review.rejected&&!pending&&automaticReplacementPreview.get(item.index)!==latest.path){selected[item.index]=latest.path;automaticReplacementPreview.set(item.index,latest.path)}if(pending){if(!Object.hasOwn(pendingSelections,item.index))pendingSelections[item.index]=latest?.path||''}else if(Object.hasOwn(pendingSelections,item.index)){if(latest&&latest.path!==pendingSelections[item.index])selected[item.index]=latest.path;delete pendingSelections[item.index]}const generating=['running','queued'].includes(s.status)&&['alignment','subjects','model','references','illustrations','cutouts'].includes(s.stage);const previews=generating?variants.filter(v=>v.current||v.raw||v.fresh):variants;let active=previews.find(v=>v.path===selected[item.index])||previews.find(v=>v.current)||previews[0];if(active)selected[item.index]=active.path;else delete selected[item.index];const stage=document.createElement('div');stage.className='image-stage';if(pending)stage.setAttribute('aria-busy','true');if(pending&&!active){stage.classList.add('image-pending');stage.textContent=pending+'…';stage.setAttribute('aria-busy','true')}else if(active){appendStableArtwork(stage,active,item,previousImages.get(item.index));if(pending){const status=document.createElement('span');status.className='image-progress-label';status.textContent=pending+'…';status.setAttribute('role','status');stage.append(status)}}else{stage.textContent='Waiting to generate…';stage.style.color='#5b6252'}
// red marks at the lower right: the checker rejected this picture; a reference it shows failed its check or is being repainted, so it is painted again
const mark=(cls,glyph,title)=>{const m=document.createElement(cls==='rejected'?'button':'span');m.className='image-mark '+cls;m.textContent=glyph;m.title=title;m.setAttribute('aria-label',title);if(cls==='rejected'){m.type='button';m.onclick=event=>{event.stopPropagation();openFailedImages({index:item.index,name:'Illustration '+(item.index+1),history:item.variants.filter(v=>v.review?.rejected).map(v=>({url:v.url,review:v.review}))})}}else m.setAttribute('role','img');stage.append(m)};
if(active?.review?.force_used)mark('forced','✓','Force used · checker skipped. Originally rejected: '+[active.review.original_review?.summary,...(active.review.original_review?.issues||[]).map(i=>typeof i==='string'?i:i.issue)].filter(Boolean).join('; '));
else if(active?.review?.rejected)mark('rejected','✕','Rejected by the checker'+(active.review.summary?': '+active.review.summary:''));
else if(active?.review&&!active.review.validation_pending&&!active.review.manual_skip&&Number.isFinite(active.review.score))mark('passed','✓','Passed the checker'+(active.review.summary?': '+active.review.summary:''));
const refs=(s.entity_references||[]).filter(e=>(e.segments||[]).includes(item.index+1));
const repainting=refs.filter(e=>e.rejected||(s.queued_actions||[]).some(q=>q.action==='reference'&&q.entity===e.id));
if(item.reason==='reference'||queued?.reason==='reference'||(repainting.length&&(pending||queued)))mark('dependent','↻','Painted again because its reference '+(repainting.length?repainting.map(e=>e.name+(e.rejected?' failed the check':' is being repainted')).join(', '):'failed the check'));
const body=document.createElement('div');body.className='card-body';const title=document.createElement('div');title.className='card-title';const heading=document.createElement('h3');heading.textContent='Illustration '+(item.index+1);const badge=document.createElement('span');badge.className='badge';badge.textContent=pending?pending:active?(active.current?'Selected':active.raw?'Raw':'Candidate'):'Queued';title.append(heading,badge);const lyric=document.createElement('div');lyric.className='lyrics';lyric.textContent=item.lyrics;const subject=document.createElement('div');subject.className='subject';subject.textContent=item.subject;subject.title=item.subject;body.append(title,lyric,subject);const strip=document.createElement('div');strip.className='variants';variants.forEach(v=>{const b=button('',()=>{selected[item.index]=v.path;gallerySignature='';renderGallery(s)});b.className='variant'+(v.path===active?.path?' selected':'');b.disabled=generating&&!v.current&&!v.raw&&!v.fresh;b.title=b.disabled?'Previous attempt · available after this generation finishes':v.current?'Current selection':v.raw?'Raw generation':'Alternative';const img=document.createElement('img');img.src=v.url;img.alt=b.title;b.append(img);
 // An alternative (never the picture in use or the raw painting) can be deleted: a cross shows at its top right on
 // hover; the first click arms it ("Delete?"), the second deletes, so a stray click costs nothing.
 const wrap=document.createElement('span');wrap.className='variant-wrap';wrap.append(b);
 if(!v.current&&!v.raw){const del=document.createElement('button');del.type='button';del.className='variant-delete';del.textContent='\u00d7';del.title='Delete this alternative';del.setAttribute('aria-label','Delete this alternative picture');
  del.onclick=async ev=>{ev.stopPropagation();ev.preventDefault();
   if(del.dataset.armed!=='1'){del.dataset.armed='1';del.textContent='Delete?';del.title='Click again to delete';setTimeout(()=>{del.dataset.armed='';del.textContent='\u00d7';del.title='Delete this alternative'},3000);return}
   del.disabled=true;
   try{const r=await api(`/api/jobs/${jobId}/discard`,{index:item.index,path:v.path});if(r.error)throw Error(r.error);if(selected[item.index]===v.path)delete selected[item.index];wrap.remove();toast(r.message||'Deleted.');gallerySignature='';if(typeof poll==='function')poll()}
   catch(e){del.disabled=false;toast(e.message||String(e))}};
  wrap.append(del)}
 strip.append(wrap)});body.append(strip);const actions=document.createElement('div');actions.className='card-actions';actions.append(button(active?.current?'Selected image':active?.review?.rejected?'Rejected image':active&&!active.raw&&!active.review&&$('autoVerify').checked?'Waiting for validation':'Use image',()=>action('select',{index:item.index,path:active.path}),!editable||!active||active.current||active.raw||active.review?.rejected||!active.review&&$('autoVerify').checked||!variants.some(v=>v.current)));const verifyReason=!(['review','complete'].includes(s.status)||stoppedVideo)?'Verify is available at artwork review or once a video exists.':!active?'Select an image first.':!$('visionModel').value?'Choose a vision model to verify images.':'';const busy=!!s.action||s.status==='running';if(active?.url)actions.append(button('Edit image',()=>window.editInImageMaker?.({id:'illustration-'+item.index,index:item.index,type:'illustration',name:'Illustration '+(item.index+1),url:active.url}),false));actions.append(button('Replace Scene',()=>openRegeneration(item.index,promptSource(item,active).subject||item.subject,promptSource(item,active).prompt??item.prompt,active,item.style,{canReplace:canRegenerate,verifyReason,busy,video:!!s.video}),!canRegenerate&&!!verifyReason));actions.append(button('Upload image or video',()=>{const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.m4v,.mkv,.avi';input.onchange=()=>{if(input.files[0]){const form=new FormData();form.append('index',item.index);form.append('replacement',input.files[0]);action('replace',form)}};input.click()},!editable));body.append(actions);if(active?.video){const note=document.createElement('div');note.className='help';note.textContent='Video clip · plays behind its lyrics until the next background. Choose its start frame in the stem timeline.';body.append(note)}if(s.dirty.includes(item.index)&&s.video){const note=document.createElement('div');note.className='dirty';note.textContent='Image changed · the video still shows the old picture. ';const open=button('Show rebuild',()=>window.showRebuildPanel());open.className='link';note.append(open);body.append(note)}if(active&&!active.raw&&!active.review){const note=document.createElement('div');note.className='help';note.textContent='Not reviewed - Verify checks visible anatomy and lettering.';body.append(note)}if(active?.review){const review=document.createElement('div');review.className='review-result'+(active.review.rejected?' flagged':'');review.textContent=(active.review.validation_pending?'Validation pending · Verify to retry':Number.isFinite(active.review.score)?`Quality ${active.review.score}% · ${active.review.rejected?'Rejected':'Accepted'} · threshold ${active.review.threshold??50}%`:'Legacy review · Verify again for a score')+'\n'+active.review.summary+(active.review.issues?.length?'\n'+active.review.issues.map(i=>`${i.severity}: ${i.location?i.location+' - ':''}${i.issue}`).join('\n'):'')+(active.review.hand_checks?.length?'\n'+active.review.hand_checks.map(h=>`${h.hand}: ${h.visible_fingers??'unclear'} visible digits ? ${h.assessment}`).join('\n'):'')+(active.review.uncertain?'\nSome details are uncertain.':'');body.append(review)}card.append(stage,body);gallery.append(card)}}
const renderGalleryWithoutSkip=renderGallery;
let typographySignature='';
function renderTypographyPictures(s){
 const items=s.ornaments||[];
 const signature=JSON.stringify([items.map(item=>[item.key,item.url,item.subject,item.source,item.keep]),s.status,s.stage]);
 if(signature===typographySignature)return;
 typographySignature=signature;
 const panel=$('smallImagePanel'),strip=$('smallImageGallery');strip.replaceChildren();
 // The tab shows only once the 3D stage painted small pictures; with none there is nothing to show.
 panel.hidden=!items.length;if(!items.length)return;
 for(const item of items){
  const card=document.createElement('figure');card.className='typography-picture';card.title=item.subject;
  const img=document.createElement('img');img.src=item.url;img.alt=item.subject||item.word;img.loading='lazy';
  img.onclick=()=>zoomPicture(item.url,'Typography picture · '+item.word);
  const caption=document.createElement('figcaption');caption.textContent=item.word?item.word+' · '+item.subject:item.subject+(item.fresh?' · just painted':'');
  card.append(img,caption);
  if(item.source!=='library'&&!item.fresh){  // a picture just painted is placed by the stage once the set is done; keep applies then
  const keep=document.createElement('label');keep.className='check-toggle typography-keep';
  keep.title='Unticked pictures are deleted and painted anew on the next render';
  const box=document.createElement('input');box.type='checkbox';box.checked=item.keep!==false;
  box.onchange=async()=>{try{await api(`/api/jobs/${jobId}/keep-picture`,{key:item.key,keep:box.checked});item.keep=box.checked}
   catch(e){box.checked=!box.checked;toast(e.message||'Could not save that choice')}};
  keep.append(box,document.createTextNode(' Keep on next render'));
  card.append(keep)}strip.append(card);
 }
}
renderGallery=function(s){
 renderGalleryWithoutSkip(s);
 renderTypographyPictures(s);
 for(const item of s.images){
  const active=item.variants.find(v=>v.path===selected[item.index]);
  const card=$('gallery').querySelector(`[data-image-index="${item.index}"]`);
  const actions=card?.querySelector('.card-actions');
  if(!actions)continue;
  const old=actions.querySelector('.skip-verify');
  if(old)old.remove();
  const needsOverride = active?.review?.validation_pending || active?.review?.lettering_pending || active?.review?.rejected;
  if(active?.current&&needsOverride&&(['review','complete'].includes(s.status)||s.status==='cancelled'&&s.stage==='review')){
   const label = active.review?.rejected ? 'Accept anyway' : 'Skip verification';
   const skip=button(label,()=>action('skip-verify',{index:item.index,path:active.path}),!!s.action);
   skip.classList.add('skip-verify');
   skip.title='Accept this image and proceed to render.';
   actions.append(skip);
  }
  if(active?.review?.manual_skip){
   const review=card.querySelector('.review-result');
   if(review)review.textContent=(active.review.manual_selection?'Chosen by hand':'Verification skipped manually')+'\n'+active.review.summary;
  }
 }
};
let renderSettingsJob=null;
// The Artwork tab's reference strip: the project's own reference photos, then each recurring character, object or
// place with the picture painted for it (the cast is shown as using the user's photo). Click a picture to enlarge it.
let artworkRefsSignature='';
// [1,2,3,16,18,19] -> 'Images 1-3, 16, 18-19'
function imageRanges(numbers){
 const list=[...new Set(numbers||[])].sort((a,b)=>a-b),parts=[];
 for(let k=0;k<list.length;k++){let end=k;while(end+1<list.length&&list[end+1]===list[end]+1)end++;
  parts.push(end>k?`${list[k]}\u2013${list[end]}`:String(list[k]));k=end}
 return parts.length?(list.length>1?'Images ':'Image ')+parts.join(', '):'';
}
// A studio started before it sent entity_references still serves them in the storyline (/story): read them from there,
// at most every 20 seconds, so the recurring references show without restarting the studio.
let storyEntities={job:'',at:0,list:null,loading:false};
function entityReferences(s){
 if(Array.isArray(s?.entity_references))return s.entity_references;
 const job=typeof jobId!=='undefined'?jobId:'';
 if(!job)return [];
 if(storyEntities.job!==job)storyEntities={job,at:0,list:null,loading:false};
 if(!storyEntities.loading&&Date.now()-storyEntities.at>20000){
  storyEntities.loading=true;
  api(`/api/jobs/${job}/story`).then(data=>{
   if(storyEntities.job!==job)return;
   storyEntities.list=(data?.entities||[]).map(e=>({id:e.id||'',name:e.name,kind:e.kind,cast:!!e.cast,uploaded:!!e.uploaded,
    segments:(e.segments||[]).map(i=>i+1),url:e.image||null}));
   artworkRefsSignature='';renderArtworkRefs(typeof state!=='undefined'?state:null);
  }).catch(()=>{}).finally(()=>{storyEntities.loading=false;storyEntities.at=Date.now()});
 }
 return storyEntities.list||[];
}
function renderArtworkRefs(s){
 const host=document.getElementById('artworkRefs');if(!host)return;
 const photos=s?.render_settings?.references||[],entities=entityReferences(s);
 recoverForcedReferences(entities);
 const sig=JSON.stringify([photos,entities,(s?.queued_actions||[]).filter(q=>q.action==='reference').map(q=>q.entity)]);if(sig===artworkRefsSignature)return;artworkRefsSignature=sig;
 host.replaceChildren();host.hidden=!photos.length&&!entities.length;if(host.hidden)return;
 const group=(title,help)=>{const box=document.createElement('div');box.className='artwork-ref-group';
  const head=document.createElement('div');head.className='artwork-ref-head';head.innerHTML='<strong></strong> <span class="help"></span>';
  head.querySelector('strong').textContent=title;head.querySelector('.help').textContent=help;
  const row=document.createElement('div');row.className='artwork-ref-row';box.append(head,row);host.append(box);return row};
 const card=(row,url,name,detail)=>{const item=document.createElement('figure');item.className='artwork-ref'+(url?'':' pending');
  let entityId='';if(detail&&typeof detail==='object'){entityId=detail.entity||'';detail=detail.text||''}  // a recurring reference: its earlier pictures open with it
  if(url){const img=document.createElement('img');img.src=url;img.alt=name;img.loading='lazy';if(entityId)img.dataset.entity=entityId;item.append(img)}
  else{const box=document.createElement('div');box.className='artwork-ref-empty';box.textContent=/^Queued for repaint/.test(detail||'')?'Queued for repaint':/^Described/.test(detail||'')?'Place: no picture':/^Your photo/.test(detail||'')?'Uses your photo':'Not painted yet';item.append(box)}
  const caption=document.createElement('figcaption');caption.textContent=name;if(detail){const d=document.createElement('small');d.textContent=detail;caption.append(d)}
  if(url&&window.tagCaption)caption.append(tagCaption(entityId?referenceTag(name):'@photo'+String(name).replace(/\D/g,'')));
  item.append(caption);item.title=name+(detail?' · '+detail:'');row.append(item)};
 if(photos.length){const row=group('Your reference photos','');photos.forEach((url,i)=>card(row,url,'Photo '+(i+1),''))}
 const painted=entities;  // keep every character's placeholder visible while its sheet is pending
 if(painted.length){const row=group('Recurring in the story','Painted once each and given to every scene that shows them; a changed form is painted from the sheet of the one it comes from.');
  window.referenceEarlier=Object.fromEntries(painted.filter(e=>e.id&&(e.earlier?.length||e.history?.length)).map(e=>[e.id,{name:e.name,current:e.url||'',earlier:e.earlier||[],history:e.history||[]}]));
  for(const e of painted){const where=imageRanges(e.segments),queued=(s?.queued_actions||[]).some(q=>q.action==='reference'&&q.entity===e.id);
   card(row,e.url||null,e.name,{text:queued?'Queued for repaint · '+where:e.stale?'Old picture · repainted with the next image · '+where:e.cast&&s?.render_settings?.cast_reference?'From your photo · '+where:where,entity:e.id});
   const forced=forcedReference(e);
   if(e.rejected&&!forced){const fig=row.lastElementChild,m=document.createElement('button');m.type='button';m.className='artwork-ref-mark';m.textContent='✕';
    m.title='Rejected by the checker'+(e.issues?.length?': '+e.issues.join('; '):'');m.setAttribute('aria-label',m.title);m.onclick=event=>{event.stopPropagation();openFailedImages(e)};fig.append(m)}
   if(forced){const fig=row.lastElementChild,m=button('✓',()=>openFailedImages(e));m.className='artwork-ref-mark forced';m.title='Force used · checker skipped. Originally rejected: '+[forced.summary,...(forced.issues||[]).map(i=>typeof i==='string'?i:i.issue)].filter(Boolean).join('; ');m.setAttribute('aria-label',m.title);fig.append(m)}
   else if(e.check_passed){const fig=row.lastElementChild,m=document.createElement('span');m.className='artwork-ref-mark passed';m.textContent='✓';m.title='Passed the checker'+(e.check_summary?': '+e.check_summary:'');m.setAttribute('role','img');m.setAttribute('aria-label',m.title);fig.append(m)}
   if(e.updated_at&&e.url){const fig=row.lastElementChild,key='referenceSeen:'+jobId+':'+e.id;let seen='';try{seen=localStorage.getItem(key)||''}catch{}if(seen!==e.url){fig.classList.add('reference-updated');fig.querySelector('img')?.addEventListener('click',()=>{fig.classList.remove('reference-updated');try{localStorage.setItem(key,e.url)}catch{}},{once:true})}}
   if(e.id){const fig=row.lastElementChild,queued=(s?.queued_actions||[]).some(q=>q.action==='reference'&&q.entity===e.id);
    const b=document.createElement('button');b.type='button';b.className='artwork-ref-repaint';b.textContent=queued?'\u23F3':'\u21BB';
    b.disabled=queued;b.title=queued?'Repaint queued':'Repaint '+e.name+': edit its prompt, then paint it and the images that show it again';
    b.setAttribute('aria-label',b.title);b.onclick=()=>openReferenceRepaint(e);fig.append(b,replaceButtons(e))}}}
}
window.renderArtworkRefs=renderArtworkRefs;
const forceKey=(project,id)=>'forcedReference:'+project+':'+id;
function forcedReference(entity){
 if(entity.force_used)return entity.force_review||{};
 try{const saved=JSON.parse(localStorage.getItem(forceKey(jobId,entity.id))||'null');if(saved&&saved.url?.split('?')[0]===entity.url?.split('?')[0])return saved.review||{}}catch{}
 return null;
}
let forceRecovery={job:'',at:0,busy:false};
function recoverForcedReferences(entities){
 if(forceRecovery.busy||!entities.some(e=>e.rejected&&!forcedReference(e))||forceRecovery.job===jobId&&Date.now()-forceRecovery.at<5000)return;
 const project=jobId;forceRecovery={job:project,at:Date.now(),busy:true};
 api(`/api/jobs/${project}/story`).then(story=>{let changed=false;for(const e of entities){const saved=story.entities?.find(s=>s.id===e.id);if(e.rejected&&saved?.uploaded&&saved.image?.split('?')[0]===e.url?.split('?')[0]){try{localStorage.setItem(forceKey(project,e.id),JSON.stringify({url:e.url,review:{summary:'Rejected by the checker before manual selection.',issues:e.issues||[]}}));changed=true}catch{}}}if(changed&&jobId===project){artworkRefsSignature='';renderArtworkRefs(state)}}).catch(()=>{}).finally(()=>{forceRecovery.busy=false});
}
function openFailedImages(entity){
 const project=jobId,dialog=document.createElement('dialog');dialog.className='modal failed-images';
 const heading=document.createElement('h3');heading.textContent='Rejected images · '+entity.name;
 const close=button('Close',()=>dialog.close());const grid=document.createElement('div');grid.className='failed-image-grid';
 const status=document.createElement('p');status.className='help';status.setAttribute('role','status');
 let attempts=(entity.history||[]).filter(h=>h.review?.passed===false||h.review?.rejected);
 if(!attempts.length)attempts=[...new Set([entity.url,...(entity.earlier||[])].filter(Boolean))].map(url=>({url,review:{summary:'Earlier checker results may not have been saved.',issues:entity.issues||[]}}));
 for(const attempt of attempts){
  const card=document.createElement('figure'),img=document.createElement('img');img.src=attempt.url;img.alt=entity.name;img.loading='lazy';img.onclick=()=>zoomPicture(attempt.url,entity.name);
  const why=document.createElement('p');why.textContent=[attempt.review?.summary,...(attempt.review?.issues||[]).map(i=>typeof i==='string'?i:i.issue)].filter(Boolean).join('\n')||'No explanation was saved.';
  const use=button('Force-use image and skip checker',async()=>{
   use.disabled=true;status.textContent='Applying selected image…';
   try{const response=await fetch(attempt.url);if(!response.ok)throw Error('Image is no longer available');const form=new FormData();
    form.append('force_use','true');form.append('force_review',JSON.stringify(attempt.review||{}));
    if(entity.id){form.append('id',entity.id);form.append('picture',await response.blob(),'forced-reference.png');await api(`/api/jobs/${project}/story-entities`,form)}
    else{form.append('index',entity.index);form.append('replacement',await response.blob(),'forced-image.png');await api(`/api/jobs/${project}/replace`,form)}
    if(entity.id){const fresh=await api(`/api/jobs/${project}`);const selected=fresh.entity_references?.find(e=>e.id===entity.id);if(selected?.url)try{localStorage.setItem(forceKey(project,entity.id),JSON.stringify({url:selected.url,review:attempt.review||{}}))}catch{}}
    status.textContent='Selected. This image will be used without further checking.';gallerySignature='';artworkRefsSignature='';await window.poll?.();dialog.close();
   }catch(error){status.textContent=error.message;use.disabled=false}
  });
  const edit=button('Edit image / prompt',()=>{dialog.close();if(entity.id)window.editInImageMaker?.({id:entity.id,name:entity.name,url:attempt.url});else{const item=state?.images?.find(i=>i.index===entity.index);const variant=item?.variants?.find(v=>v.url===attempt.url);if(item&&variant)openRegeneration(item.index,item.subject,variant.prompt||item.prompt,variant,item.style,{canReplace:true})}});
  card.append(img,why,use,edit);grid.append(card);
 }
 if(!attempts.length)status.textContent='No saved failed image is available for this reference yet.';
 dialog.append(heading,close,grid,status);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
}
// Swap a recurring reference's picture: a file of the user's own, or an edit of this one in Image Maker.
function replaceButtons(entity){
 const row=document.createElement('div');row.className='artwork-ref-replace';
 const file=Object.assign(document.createElement('input'),{type:'file',accept:'image/png,image/jpeg,image/webp',hidden:true});
 const upload=button('Upload',()=>file.click());upload.title='Replace '+entity.name+' with a picture of your own';
 const source=entity.url||entity.history?.find(h=>h.review?.passed===false)?.url||entity.earlier?.[0];
 const edit=button('Edit',()=>window.editInImageMaker?.({id:entity.id,name:entity.name,url:entity.url}));edit.disabled=!entity.url;edit.title=entity.url?'Edit '+entity.name+' while keeping everything else unchanged':'This reference is waiting to be painted; use the regenerate arrow';
 file.onchange=async()=>{const picture=file.files[0];file.value='';if(!picture)return;
  const form=new FormData();form.append('id',entity.id);form.append('picture',picture);
  try{const r=await api(`/api/jobs/${jobId}/story-entities`,form);if(r.error)throw Error(r.error);toast(r.message||'Replaced.');gallerySignature='';if(typeof poll==='function')poll()}
  catch(e){toast('Could not replace the picture: '+(e.message||e))}};
 row.append(upload,edit,file);return row}
// The illustration's own reference pictures (the storyline segment's, at most 3): they lead for this image alone,
// unlike the project's references above, which every image gets. Added or removed here as in the storyline panel;
// a replacement or verify made afterwards uses them.
async function renderRegenerateOwnRefs(){
 const row=$('regenerateOwnRow'),list=$('regenerateOwnRefs'),add=$('regenerateOwnAdd');if(!row||!list||!add||!jobId)return;
 const index=regenerateIndex;let refs=[],uploads=[];
 try{const data=await api(`/api/jobs/${jobId}/story`);const segment=(data?.segments||[]).find(s=>+s.index===index)||(data?.segments||[])[index];refs=segment?.references||[];uploads=data?.uploads||[]}
 catch{refs=[]}
 if(regenerateIndex!==index)return;
 const earlier=$('regenerateOwnEarlier'),spare=uploads.filter(u=>!refs.some(r=>r.path===u.name));
 if(earlier){earlier.hidden=!spare.length;earlier.querySelector('div').replaceChildren(...spare.map(u=>{
  const pick=document.createElement('button');pick.type='button';pick.className='reuse-pick';pick.title='Use '+u.name+' for this illustration';
  const img=document.createElement('img');img.src=u.url;img.alt=u.name;const name=document.createElement('small');name.textContent=u.name;pick.append(img,name);
  pick.onclick=async()=>{try{const r=await api(`/api/jobs/${jobId}/story-reference`,{index,reuse:u.path});if(r.error)throw Error(r.error);toast(r.message||'Added.');renderRegenerateOwnRefs()}
   catch(e){toast('Could not add the picture: '+(e.message||e))}};
  const drop=document.createElement('button');drop.type='button';drop.className='reuse-drop';drop.textContent='×';drop.title='Delete '+u.name;drop.setAttribute('aria-label',drop.title);
  drop.onclick=async()=>{try{const r=await api(`/api/jobs/${jobId}/story-upload-delete`,{path:u.path});if(r.error)throw Error(r.error);toast(r.message||'Deleted.');renderRegenerateOwnRefs()}
   catch(e){toast(/not found|unknown/i.test(String(e.message||e))?'Restart the studio to delete uploads.':(e.message||String(e)))}};
  const item=document.createElement('div');item.className='reuse-ref';item.append(pick,drop);
  return item}))}
 list.replaceChildren(...refs.map(ref=>{
  const div=document.createElement('div');div.className='ref saved';const img=document.createElement('img');img.src=ref.url;img.alt='Reference for illustration '+(index+1);
  div.append(img,button('×',async()=>{try{const r=await api(`/api/jobs/${jobId}/story-reference-remove`,{index,path:ref.path});if(r.error)throw Error(r.error);toast(r.message||'Removed.');renderRegenerateOwnRefs()}
   catch(e){toast('Could not remove the picture: '+(e.message||e))}}),tagCaption(referenceTag(ref.path)));
  return div}));
 if(!refs.length)list.append(Object.assign(document.createElement('span'),{className:'help',textContent:'None: this image is painted from the project\'s references and its recurring ones.'}));
 add.hidden=refs.length>=3;
}
$('regenerateOwnFile')?.addEventListener('change',async event=>{
 const files=[...event.target.files].slice(0,3);event.target.value='';if(!files.length||!jobId)return;
 const index=regenerateIndex;
 if(typeof imageModelTakesReferences==='function'&&!imageModelTakesReferences())toast(`${$('imageModel')?.selectedOptions[0]?.textContent||'This image model'} does not read reference images: this illustration ignores them until an image model that takes references is chosen.`);
 for(const file of files){  // the route takes one picture at a time
  const form=new FormData();form.append('index',String(index));form.append('reference',file);
  try{const r=await api(`/api/jobs/${jobId}/story-reference`,form);if(r.error)throw Error(r.error);toast(r.message||'Added.')}
  catch(e){toast('Could not add the picture: '+(e.message||e));break}
 }
 renderRegenerateOwnRefs();
});
if($('regenerateModal'))new MutationObserver(()=>{if($('regenerateModal').open)renderRegenerateOwnRefs()}).observe($('regenerateModal'),{attributes:true,attributeFilter:['open']});
// Repaint a recurring reference: its prompt, editable, then the picture and the images that show it are painted again.
async function openReferenceRepaint(entity){return window.openReferenceRegeneration(entity)}
// The Replace dialog's recurring references for this image: the storyline's characters, objects and places tagged in
// it, each removable, and a picker to add another. The next Replace (and Resume, and the clip) follows the change.
function renderRegenerateEntities(){
 const row=document.getElementById('regenerateEntityRow'),list=document.getElementById('regenerateEntities'),add=document.getElementById('regenerateEntityAdd');
 if(!row||!list||!add)return;
 const all=entityReferences(state).filter(e=>e.name&&!e.cast),index=regenerateIndex;  // the cast is a project photo, listed above as @photo1
 row.hidden=!all.length;if(!all.length)return;
 const tagged=all.filter(e=>(e.segments||[]).includes(index+1)),others=all.filter(e=>!tagged.includes(e));
 const change=async(entity,on)=>{
  try{const r=await api(`/api/jobs/${jobId}/story-entity`,{index,id:entity.id,on});if(r.error)throw Error(r.error);
   if(state)state.entity_references=r.entity_references||[];renderRegenerateEntities();window.renderArtworkRefs?.(state);toast(r.message)}
  catch(e){toast(/not found|unknown/i.test(String(e.message||e))?'Restart the studio to add or remove references here; they show already.':'Could not change the references: '+(e.message||e))}};
 list.replaceChildren(...tagged.map(e=>{
  const chip=document.createElement('div');chip.className='ref regen-entity';chip.title=e.name;
  if(e.url){const img=document.createElement('img');img.src=e.url;img.alt=e.name;chip.append(img)}
  else{const box=document.createElement('span');box.className='regen-entity-empty';box.textContent='not painted';chip.append(box)}
  const name=document.createElement('small');name.textContent=e.name;chip.append(name);if(e.url&&window.tagCaption)chip.append(tagCaption(referenceTag(e.name)));  // a picture the model gets: the tag to name it by
  const drop=document.createElement('button');drop.type='button';drop.textContent='×';drop.title='Remove from this image';drop.onclick=()=>change(e,false);chip.append(drop);
  return chip}));
 if(!tagged.length)list.append(Object.assign(document.createElement('span'),{className:'help',textContent:'None in this image.'}));
 add.replaceChildren(new Option(others.length?'+ Add reference…':'All references are in this image',''),...others.map(e=>new Option(e.name,e.id)));
 add.disabled=!others.length;
 add.onchange=()=>{const e=others.find(x=>x.id===add.value);if(e)change(e,true)};
}
window.renderRegenerateEntities=renderRegenerateEntities;
