// Job lifecycle: restoring render settings, polling the running job, applying each update and start-up.
function restoreRenderSettings(s){
 if(!s.render_settings||renderSettingsJob===jobId)return;
 const settings=s.render_settings;
 if(settings.image_model&&[...$('imageModel').options].some(o=>o.value===settings.image_model))$('imageModel').value=settings.image_model;
 if(settings.effect_speeds&&$('effectSpeeds'))$('effectSpeeds').value=JSON.stringify(settings.effect_speeds);
 if(settings.effect_intensities&&$('effectIntensities'))$('effectIntensities').value=JSON.stringify(settings.effect_intensities);
 if(settings.kinetic&&$('kinetic')){$('kinetic').value=JSON.stringify(settings.kinetic);window.syncKineticControls?.()}
 if(Array.isArray(settings.lettering_styles)&&$('letteringStyles')){$('letteringStyles').value=JSON.stringify(settings.lettering_styles);window.syncLetteringChecks?.()}
 if($('projectName')&&settings.name!==undefined)$('projectName').value=settings.name;
 if($('lyrics')&&typeof settings.lyrics==='string'){setSongTimings(null);$('lyrics').value=settings.lyrics;lineCount();speechInfo()}
 if($('style')&&settings.theme)$('style').value=settings.theme;
 if($('referencePrompt')&&settings.style_prompt)$('referencePrompt').value=settings.style_prompt;
 if($('language')&&settings.language&&[...$('language').options].some(o=>o.value===settings.language))$('language').value=settings.language;
 if(settings.lines!==undefined)applyLyricSplit(parseLyricSplit({lyric_split:settings.lines}));
 savedWordTimingsAvailable=!!settings.has_word_timings;
 $('protectWordAlignment').disabled=!savedWordTimingsAvailable&&!currentSongTimings();
 $('protectWordAlignment').checked=!!settings.protect_word_alignment;
 $('editLyricsTimeline').hidden=!savedWordTimingsAvailable&&!currentSongTimings();
 speechInfo();
 window.savedReferences=Array.isArray(settings.references)?settings.references:[];
 // A project with its own references never takes the bundled default picture the empty form starts with: it would be
 // uploaded on the next run and painted into every scene beside the project's own.
 if(window.savedReferences.length&&refs.some(r=>r.asset)){refs.filter(r=>r.asset).forEach(r=>URL.revokeObjectURL(r.url));refs=refs.filter(r=>!r.asset)}
 showRefs();
 for(const name of ['image_instructions','story_prompt','stage_pictures','instructions','reading_flow','font_family','font_style','font_scale','text_animation','audio_mode','type_effect','entrance_effect','exit_effect','particle_intensity','particle_speed','video_upscale','scene_direction','picture_kinds','end_frame_model','depth_model']){
  const el=$('jobForm').elements.namedItem(name);if(!el||settings[name]===undefined)continue;
  const value=name==='image_instructions'&&isImportedSongMeaning(settings[name])?'':String(settings[name]);
  el.value=el.tagName==='SELECT'&&![...el.options].some(o=>o.value===value)?'none':value;
 }
 window.syncKineticControls?.();window.showPictureKinds?.();
 if(typeof settings.auto_accept==='boolean')$('autoAccept').checked=settings.auto_accept;
 if(typeof settings.review_references==='boolean'&&$('reviewReferences'))$('reviewReferences').checked=settings.review_references;
 if(typeof settings.repaint_references==='boolean'&&$('repaintReferences'))$('repaintReferences').checked=settings.repaint_references;
 if(typeof settings.end_frame_review==='boolean'&&$('endFrameReview'))$('endFrameReview').checked=settings.end_frame_review;
 window.showCheckPrompts?.(settings);
 if(typeof settings.auto_verify==='boolean')$('autoVerify').checked=settings.auto_verify;
 if(typeof settings.cast_reference==='boolean')$('castReference').checked=settings.cast_reference;
  if(settings.image_seed!==undefined&&$('imageSeed')){
   $('randomizeSeed').checked=true;
   $('imageSeed').value='';
   $('imageSeed').placeholder='Random per image (last run '+settings.image_seed+')';
  }
 restoreParticlePools(settings);if($('textAnimation').value==='ai'&&!window.aiTypographyAvailable)$('textAnimation').value='mixed';if(window.refreshTypographyLabels)refreshTypographyLabels();updateDensity();updateSpeed();refreshSidebarLabels();renderSettingsJob=jobId;
}
function update(s){s=showOptimisticQueue(s);restoreRenderSettings(s);state=s;window.renderArtworkRefs?.(s);refreshProjectPipelineLive(s);updateRebuildNotice(s);const active=['running','queued','review'].includes(s.status);renderProductionHeader(s);$('actionProgress').textContent='';  /* the status and the queue in the header say what runs and what waits */$('cancel').disabled=!(active||s.action);$('verifyAll').disabled=!['review','complete'].includes(s.status)||!!s.action||(!$('visionModel').value||!$('autoVerify').checked);updateGenerate();$('reviewBanner').style.display=s.status==='review'?'flex':'none';$('approve').disabled=!!s.action||!!s.queued_actions?.length||!!s.rejected_images?.length;$('elapsed').textContent=timeText(s.elapsed)+' elapsed'+remainingText(s);const ready=s.images.filter(i=>i.variants.some(v=>v.current)).length;$('imageCount').textContent=`${ready}/${s.images.length||'—'} images ready`;renderProductionStages(s);const history=s.history.length?s.history:[[0,0]];const maxTime=Math.max(1,s.elapsed,history.at(-1)[0]);const points=[[0,0],...history].map(([t,p])=>[30+360*t/maxTime,130-115*p/100]);const d=stepPath(points);$('chartLine').setAttribute('d',d);$('chartArea').setAttribute('d',d+` L${points.at(-1)[0]} 130 L30 130 Z`);$('chartTime').textContent=timeText(maxTime);renderProgressChart(s,history,maxTime);if(s.logs.length){logs.push(...s.logs);renderLogs()}cursor=s.cursor;renderGallery(s);updateVideoHistory(s);window.syncTimeline?.(s,jobId)}
let typographyFallbackJob='',typographyFallback=[],typographyFallbackTime=0;
async function hydrateTypographyPictures(s,id){
 if(s.ornaments?.length)return;
 if(typographyFallbackJob===id&&typographyFallback.length){s.ornaments=typographyFallback;return}
 if(s.status==='running'&&s.stage!=='render')return;
 if(typographyFallbackJob===id&&Date.now()-typographyFallbackTime<15000)return;
 typographyFallbackJob=id;typographyFallbackTime=Date.now();
 try{
  const response=await fetch(`/files/${id}/video.blocks.json`,{cache:'no-store'});if(!response.ok)return;
  const record=await response.json();const pictures=(record.blocks||[]).map(b=>b?.ornament).filter(o=>o?.library&&!o?.image);
  const valid=[];
  for(const ornament of pictures){
   const kind=ornament.library;if(!/^[a-z0-9-]+$/.test(kind))continue;
   const url=`/files/${id}/video.picture-previews/${kind}.png`;
   if(!(await fetch(url,{cache:'no-store'})).ok)continue;
   valid.push({word:ornament.text||'',subject:ornament.subject||kind,source:'library',line:ornament.line,
               url,key:`${ornament.line}:${ornament.word}`,keep:true});
  }
  typographyFallback=valid;s.ornaments=valid;
 }catch{}
}
let polling=false;async function poll(){if(!jobId||polling)return;polling=true;const expected=jobId;try{const s=await api(`/api/jobs/${jobId}?cursor=${cursor}`);await hydrateLiveArtwork(s,expected);await hydrateTypographyPictures(s,expected);if(jobId===expected)update(s)}catch(e){if(jobId===expected){$('message').textContent='Connection interrupted: '+e.message;$('generateReason').textContent='Cannot refresh job status. Use Reconnect or New session to recover.'}}finally{polling=false}}
async function init(){try{const cfg=await api('/api/config');token=cfg.token;$('referencePrompt').value=cfg.style_prompt;initModels(cfg);window.initProjectsFolder?.(cfg);initializeVideoControls();await initializeProfiles();const old=localStorage.getItem('lyricStudioAutoInstructions');if(isImportedSongMeaning($('imageInstructions').value)||old&&$('imageInstructions').value===old){$('imageInstructions').value='';$('imageInstructions').dispatchEvent(new Event('input',{bubbles:true}))}localStorage.removeItem('lyricStudioAutoInstructions');renderProductionStages();visibleJobs(cfg.jobs).forEach(j=>$('jobs').add(new Option(j.name+' · '+j.id,j.id)));const active=visibleJobs(cfg.jobs).find(j=>['running','queued'].includes(j.status))?.id;const saved=active||localStorage.getItem('lyricStudioJob');if(saved&&visibleJobs(cfg.jobs).some(j=>j.id===saved))setJob(saved);else if(window.updateProjectPipelineStatus)updateProjectPipelineStatus('');lineCount();$('refreshModels').click()}catch(e){toast(e.message)}}setInterval(poll,1200);

// Time left, from the progress history: the recent pace (last few minutes) blended with the whole run's, so a
// slow step (model loading) does not swing it wildly. Recomputed on every poll and counted down between polls.
let etaSeconds=null,etaAt=0;
function remainingText(s){
 const running=['running','queued'].includes(s?.status)||!!s?.action;
 // The server's estimate counts the work left in every step (images, AI video, render, Final cut) at this
 // computer's measured speeds; the progress-bar pace below is only the fallback.
 if(running&&Number.isFinite(s?.eta?.seconds)){
  etaSeconds=s.eta.seconds;etaAt=Date.now();
  const el=$('elapsed');if(el)el.title='Time left: '+(s.eta.parts||[]).map(([label,sec])=>label+' '+leftText(sec).replace(/^about |^under /,'').replace(/ left$/,'')).join(' · ');
  return ' · '+leftText(etaSeconds);
 }
 const percent=+(s?.action?s.action_percent:s?.percent)||0;
 if(!running||percent<2||percent>=99.5||!s.elapsed){etaSeconds=null;return ''}
 const history=(s.history||[]).filter(([t,p])=>Number.isFinite(t)&&Number.isFinite(p));
 const overall=percent/Math.max(1,s.elapsed);
 const recentFrom=history.find(([t])=>t>=s.elapsed-240);
 const recent=recentFrom&&s.elapsed-recentFrom[0]>=30&&percent>recentFrom[1]?(percent-recentFrom[1])/(s.elapsed-recentFrom[0]):null;
 const pace=recent?recent*.6+overall*.4:overall;
 if(!(pace>0)){etaSeconds=null;return ''}
 const estimate=(100-percent)/pace;
 etaSeconds=etaSeconds==null?estimate:etaSeconds*.7+estimate*.3;etaAt=Date.now();
 return ' · '+leftText(etaSeconds);
}
function leftText(seconds){
 seconds=Math.max(0,Math.round(seconds));
 if(seconds<60)return 'under a minute left';
 const minutes=Math.round(seconds/60);
 return minutes<60?`about ${minutes} min left`:`about ${Math.floor(minutes/60)} h ${minutes%60} min left`;
}
setInterval(()=>{
 if(etaSeconds==null)return;
 const left=etaSeconds-(Date.now()-etaAt)/1000,el=$('elapsed');
 if(el&&el.textContent.includes(' · '))el.textContent=el.textContent.split(' · ')[0]+' · '+leftText(left);
},1000);

// The progress chart's background shows which pipeline step the run was in at each moment (from the progress
// percentage, which each step fills a fixed share of); double-click opens a large, labelled version.
const PROGRESS_STEPS=[['Timing',0,8,210],['Prompts',8,14,265],['Storyline',14,18,330],['Image prompts',18,34,28],
 ['Images',34,80,140],['Review',80,82,55],['Render',82,101,185]];
const stepAt=p=>PROGRESS_STEPS.find(([,from,to])=>p>=from&&p<to)||PROGRESS_STEPS.at(-1);
function progressBands(history,maxTime){
 const bands=[];const points=[[0,0],...history];
 for(let i=0;i<points.length;i++){
  const [t,p]=points[i],end=i+1<points.length?points[i+1][0]:maxTime,step=stepAt(p);
  if(end<=t&&i+1<points.length)continue;
  const last=bands.at(-1);
  if(last&&last.step===step)last.end=end;else bands.push({step,start:t,end});
 }
 return bands.filter(b=>b.end>b.start);
}
function svgNode(name,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n}
function renderProgressChart(s,history,maxTime){
 const bands=progressBands(history,maxTime);
 const mini=$('chartBands');
 if(mini){mini.replaceChildren(...bands.map(b=>svgNode('rect',{x:30+360*b.start/maxTime,y:15,width:Math.max(.5,360*(b.end-b.start)/maxTime),height:115,fill:`hsl(${b.step[3]} 70% 55% / .16)`},null)))}
 const modal=$('progressModal');
 if(modal?.open){drawProgressDetail(history,maxTime,bands);renderProgressLogs(s)}
}
function drawProgressDetail(history,maxTime,bands){
 const host=$('progressDetail');if(!host)return;
 const W=900,H=420,L=64,R=20,T=34,B=52,w=W-L-R,h=H-T-B;
 const X=t=>L+w*t/maxTime,Y=p=>T+h*(1-p/100);
 const svg=svgNode('svg',{viewBox:`0 0 ${W} ${H}`,class:'progress-detail',role:'img','aria-label':'Overall progress (%) against elapsed time, coloured by pipeline step'});
 for(const b of bands){
  const x=X(b.start),width=Math.max(1,X(b.end)-x);
  svg.append(svgNode('rect',{x,y:T,width,height:h,fill:`hsl(${b.step[3]} 70% 55% / .18)`}));
  if(width>46)svg.append(svgNode('text',{x:x+width/2,y:T-10,'text-anchor':'middle',class:'band-label',fill:`hsl(${b.step[3]} 75% 72%)`},b.step[0]));
 }
 for(let p=0;p<=100;p+=20){
  svg.append(svgNode('line',{x1:L,x2:W-R,y1:Y(p),y2:Y(p),class:'grid'}));
  svg.append(svgNode('text',{x:L-8,y:Y(p)+4,'text-anchor':'end',class:'tick'},p+'%'));
 }
 const ticks=6;for(let k=0;k<=ticks;k++){const t=maxTime*k/ticks;
  svg.append(svgNode('line',{x1:X(t),x2:X(t),y1:T+h,y2:T+h+5,class:'axis'}));
  svg.append(svgNode('text',{x:X(t),y:T+h+20,'text-anchor':'middle',class:'tick'},timeText(t)))}
 svg.append(svgNode('line',{x1:L,x2:L,y1:T,y2:T+h,class:'axis'}));svg.append(svgNode('line',{x1:L,x2:W-R,y1:T+h,y2:T+h,class:'axis'}));
 svg.append(svgNode('text',{x:L+w/2,y:H-8,'text-anchor':'middle',class:'axis-label'},'Elapsed time (minutes:seconds)'));
 svg.append(svgNode('text',{x:16,y:T+h/2,'text-anchor':'middle',class:'axis-label',transform:`rotate(-90 16 ${T+h/2})`},'Overall progress (%)'));
 const pts=[[0,0],...history].map(([t,p])=>[X(t),Y(p)]);
 svg.append(svgNode('path',{d:stepPath(pts),class:'line'}));
 if(progressCursorX!=null)svg.append(svgNode('line',{class:'cursor',x1:progressCursorX,x2:progressCursorX,y1:T,y2:T+h}));  // kept across redraws
 host.replaceChildren(svg);
}
let progressCursorX=null;
document.querySelector('.chart-box')?.addEventListener('dblclick',()=>{
 const modal=$('progressModal');if(!modal)return;
 if(!modal.open){modal.show();modal.restorePlace?.();setProgressFollow(progressFollow)}  // floating, not modal: no backdrop, the page stays usable
 const s=state;if(s){const history=s.history?.length?s.history:[[0,0]];const maxTime=Math.max(1,s.elapsed||0,history.at(-1)[0]);renderProgressChart(s,history,maxTime);followProgressLog()}
});
$('closeProgress')?.addEventListener('click',()=>$('progressModal').close());

// Progress holds until the next report: a pause (waiting for review) is flat and a restart drops straight down,
// instead of a diagonal that looks like progress running backwards.
function stepPath(points){
 return points.map(([x,y],i)=>i?`H${x.toFixed(1)} V${y.toFixed(1)}`:`M${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
}
// The enlarged chart shows the log under it; moving over the chart highlights and scrolls to the log line written
// nearest that moment (prompt and reply dumps from the text models are left out to keep the list readable).
function progressLogEntries(s){
 const started=+s?.started||0;if(!started)return [];
 return (logs||[]).filter(l=>l&&typeof l.text==='string'&&!l.text.startsWith('|')).map(l=>({at:l.time-started,level:l.level,text:l.text}));
}
function renderProgressLogs(s){
 const host=$('progressLogs');if(!host)return [];
 const entries=progressLogEntries(s);
 if(host.dataset.count===String(entries.length))return entries;
 host.dataset.count=String(entries.length);
 host.replaceChildren(...entries.map((e,i)=>{const row=document.createElement('div');row.className='progress-log '+(e.level||'info');row.dataset.i=i;
  const t=document.createElement('time');t.textContent=timeText(Math.max(0,e.at));const text=document.createElement('span');text.textContent=e.text;row.append(t,text);return row}));
 followProgressLog();
 return entries;
}
// Follow keeps the end of the log in view as lines arrive; it stands aside while the mouse is over the chart, which
// scrolls the log to the moment under it, and takes over again when the mouse leaves.
let progressFollow=localStorage.getItem('lyricStudioProgressFollow')!=='off',progressHover=false;
function followProgressLog(){const host=$('progressLogs');if(host&&progressFollow&&!progressHover)host.scrollTop=host.scrollHeight}
function setProgressFollow(on){
 progressFollow=on;localStorage.setItem('lyricStudioProgressFollow',on?'on':'off');
 const button=$('followProgress'),modal=$('progressModal');
 if(button)button.setAttribute('aria-pressed',String(on));if(modal)modal.dataset.follow=on?'on':'off';
 if(on)followProgressLog();
}
$('followProgress')?.addEventListener('click',()=>setProgressFollow(!progressFollow));
$('progressDetail')?.addEventListener('mouseenter',()=>{progressHover=true});
$('progressDetail')?.addEventListener('mouseleave',()=>{progressHover=false;followProgressLog()});
// The panel floats (dialog.show, no backdrop) and is dragged by its head; where it was left is remembered.
(()=>{
 const modal=$('progressModal'),handle=$('progressHandle');if(!modal||!handle)return;
 const place=(x,y)=>{const w=modal.offsetWidth||600,h=modal.offsetHeight||300;x=Math.min(Math.max(0,x),Math.max(0,innerWidth-w));y=Math.min(Math.max(0,y),Math.max(0,innerHeight-Math.min(h,120)));modal.style.left=x+'px';modal.style.top=y+'px';modal.style.right='auto'};
 modal.restorePlace=()=>{try{const saved=JSON.parse(localStorage.getItem('lyricStudioProgressPlace')||'null');if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y))place(saved.x,saved.y)}catch{}};
 let drag=null;
 handle.addEventListener('pointerdown',event=>{
  if(event.button!==0||event.target.closest('button'))return;
  const box=modal.getBoundingClientRect();drag={dx:event.clientX-box.left,dy:event.clientY-box.top};
  handle.setPointerCapture(event.pointerId);modal.classList.add('dragging');event.preventDefault();
 });
 handle.addEventListener('pointermove',event=>{if(drag)place(event.clientX-drag.dx,event.clientY-drag.dy)});
 const drop=event=>{if(!drag)return;drag=null;modal.classList.remove('dragging');try{handle.releasePointerCapture(event.pointerId)}catch{}
  const box=modal.getBoundingClientRect();localStorage.setItem('lyricStudioProgressPlace',JSON.stringify({x:Math.round(box.left),y:Math.round(box.top)}))};
 handle.addEventListener('pointerup',drop);handle.addEventListener('pointercancel',drop);
 addEventListener('resize',()=>{if(modal.open&&modal.style.left)place(parseFloat(modal.style.left),parseFloat(modal.style.top))});
})();
function focusProgressLog(seconds){
 const host=$('progressLogs');const entries=progressLogEntries(state);if(!host||!entries.length)return;
 host.querySelector('.progress-log.focus')?.classList.remove('focus');
 let note=host.querySelector('.progress-log-note');
 if(seconds<entries[0].at){  // the log is kept from the run's latest start; earlier moments have none
  if(!note){note=document.createElement('div');note.className='progress-log-note help';host.prepend(note)}
  note.textContent=`No log this early: the log starts at ${timeText(entries[0].at)}, when this run last started.`;
  host.scrollTop=0;return}
 note?.remove();
 let best=0;for(let i=0;i<entries.length;i++){if(entries[i].at<=seconds)best=i;else break}
 const row=host.querySelector(`[data-i="${best}"]`);if(row){row.classList.add('focus');host.scrollTop=row.offsetTop-host.offsetTop-host.clientHeight/2}  // scroll only the log, never the dialog under the mouse
}
$('progressDetail')?.addEventListener('mousemove',event=>{
 const svg=event.currentTarget.querySelector('svg');if(!svg||!state)return;
 const box=svg.getBoundingClientRect(),W=900,L=64,R=20,w=W-L-R;
 const x=(event.clientX-box.left)*W/box.width;if(x<L||x>W-R)return;
 const history=state.history?.length?state.history:[[0,0]];const maxTime=Math.max(1,state.elapsed||0,history.at(-1)[0]);
 const seconds=(x-L)/w*maxTime;
 let cursor=svg.querySelector('.cursor');if(!cursor){cursor=svgNode('line',{class:'cursor',y1:34,y2:420-52});svg.append(cursor)}
 cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);progressCursorX=x;
 focusProgressLog(seconds);
});
