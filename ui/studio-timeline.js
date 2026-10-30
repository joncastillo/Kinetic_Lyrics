/* Timeline editor: drag words, lyric lines and illustrations against the song's audio stems. */
(()=>{
const STEMS={mix:['Full mix','#9fb7ff'],vocals:['Vocals','#ff8fb8'],drums:['Drums','#ffc46b'],bass:['Bass','#6fe0c0'],other:['Instruments','#b99bff']};
const COLOR_KEY='lyricStudioStemColors',HIDDEN_KEY='lyricStudioHiddenStems',ZOOM_KEY='lyricStudioTimelineZoom';
const MIN_WORD=.04,GAP=.01,ART_GAP=.2,EDGE=6,SNAP=7;
const H={ruler:28,art:82,line:30,word:40,stem:56};
const LINE_HUES=['#8fb4ff','#b49bff','#7fd8d0','#ffb38a','#e79bd8','#a8d98a'];
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const read=(key,fallback)=>{try{const v=JSON.parse(localStorage.getItem(key));return v??fallback}catch{return fallback}};
const write=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value))}catch{}};
const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
const clock=t=>{t=Math.max(0,t);const m=Math.floor(t/60),s=t-m*60;return String(m).padStart(2,'0')+':'+s.toFixed(2).padStart(5,'0')};

let tl=null,loadedFor='',loading=false,lastStatus='',lastVideo='';
const ui={};

function build(){
 const panel=$('timelinePanel');
 const head=el('div','panel-head tl-head');
 const title=el('div');title.append(el('h2',null,'Timeline editor'),el('small',null,'Drag words, lines and images to fix timing. Double-click a word to change its text. Hold Shift while dragging to move everything after it too.'));
 ui.badge=el('span','badge tl-badge','Saved');head.append(title,ui.badge);
 const bar=el('div','tl-toolbar');
 ui.play=button('▶ Play',togglePlay);ui.play.className='tl-play';ui.play.setAttribute('aria-label','Play or pause');
 ui.clock=el('span','tl-clock','00:00.00');
 const listen=el('label','tl-field');listen.append(el('span',null,'Listen to'));ui.listen=el('select');ui.listen.setAttribute('aria-label','Audio to play');listen.append(ui.listen);
 ui.listen.onchange=()=>setSource(ui.listen.value);
 const zoom=el('label','tl-field tl-zoom');zoom.append(el('span',null,'Zoom'));ui.zoom=el('input');Object.assign(ui.zoom,{type:'range',min:'0',max:'100',step:'1'});ui.zoom.setAttribute('aria-label','Timeline zoom');zoom.append(ui.zoom);
 ui.zoom.oninput=()=>setZoom(zoomFromSlider(+ui.zoom.value),tl?viewCenter():0);
 const follow=el('label','tl-check');ui.follow=el('input');ui.follow.type='checkbox';ui.follow.checked=true;follow.append(ui.follow,document.createTextNode(' Follow'));
 ui.undo=button('↶',undo);ui.undo.title='Undo (Ctrl+Z)';ui.undo.setAttribute('aria-label','Undo');
 ui.redo=button('↷',redo);ui.redo.title='Redo (Ctrl+Shift+Z)';ui.redo.setAttribute('aria-label','Redo');
 ui.revert=button('Discard',()=>{if(tl&&tl.dirty&&confirm('Discard unsaved timeline changes?'))load(true)});
 ui.save=button('Save',()=>save(false));
 ui.rebuild=button('Save & rebuild video',()=>save(true));ui.rebuild.className='primary';
 const transport=el('div','tl-group'),view=el('div','tl-group'),actions=el('div','tl-group tl-actions'),history=el('div','tl-history');
 history.append(ui.undo,ui.redo);transport.append(ui.play,ui.clock);view.append(listen,zoom,follow);actions.append(history,ui.revert,ui.save,ui.rebuild);
 bar.append(transport,view,actions);
 ui.now=el('div','tl-now');ui.nowArt=el('div','tl-now-art');ui.nowText=el('div','tl-now-text');ui.nowLine=el('div','tl-now-line');ui.nowNext=el('div','tl-now-next');ui.nowText.append(ui.nowLine,ui.nowNext);ui.now.append(ui.nowArt,ui.nowText);
 const overview=el('div','tl-overview');overview.append(el('div','tl-overview-label','Overview'));ui.map=el('canvas','tl-map');ui.map.setAttribute('aria-label','Song overview. Click or drag to move the view.');overview.append(ui.map);
 ui.map.addEventListener('pointerdown',e=>{ui.map.setPointerCapture(e.pointerId);ui.mapDrag=true;mapTo(e)});ui.map.addEventListener('pointermove',e=>{if(ui.mapDrag)mapTo(e)});
 ui.map.addEventListener('pointerup',()=>ui.mapDrag=false);ui.map.addEventListener('pointercancel',()=>ui.mapDrag=false);
 const body=el('div','tl-body');ui.labels=el('div','tl-labels');ui.scroller=el('div','tl-scroller');ui.track=el('div','tl-track');ui.canvas=el('canvas','tl-canvas');ui.canvas.tabIndex=0;ui.canvas.setAttribute('role','application');ui.canvas.setAttribute('aria-label','Timeline. Arrow keys move the selection, Space plays, Enter edits the word.');
 ui.track.append(ui.canvas);ui.scroller.append(ui.track);body.append(ui.labels,ui.scroller);
 ui.inspector=el('div','tl-inspector');
 ui.hint=el('div','tl-hint','Space play · ← → nudge 10 ms (Shift 100 ms) · T sets the selected word to the playhead · Ctrl+wheel zoom · Alt drag turns off snapping');
 ui.audio=new Audio();ui.audio.preload='auto';
 ui.audio.onplay=ui.audio.onpause=()=>{ui.play.textContent=ui.audio.paused?'▶ Play':'❚❚ Pause';ui.play.classList.toggle('playing',!ui.audio.paused);if(!ui.audio.paused)frame()};
 ui.editor=el('input','tl-word-input');ui.editor.hidden=true;ui.track.append(ui.editor);
 panel.append(head,bar,ui.now,overview,body,ui.inspector,ui.hint);
 ui.scroller.addEventListener('scroll',draw,{passive:true});
 new ResizeObserver(()=>{resize();draw()}).observe(ui.scroller);new ResizeObserver(()=>draw()).observe(ui.map);
 ui.canvas.addEventListener('pointerdown',pointerDown);ui.canvas.addEventListener('pointermove',pointerMove);ui.canvas.addEventListener('pointerup',pointerUp);ui.canvas.addEventListener('pointercancel',pointerUp);
 ui.canvas.addEventListener('pointerleave',()=>{if(tl&&!tl.drag){tl.hover=null;draw()}});
 ui.canvas.addEventListener('dblclick',doubleClick);ui.canvas.addEventListener('keydown',keyDown);
 ui.scroller.addEventListener('wheel',wheel,{passive:false});
 window.addEventListener('beforeunload',e=>{if(tl?.dirty){e.preventDefault();e.returnValue=''}});
}

/* ---------- loading ---------- */
window.syncTimeline=(s,id)=>{
 const panel=$('timelinePanel');if(!panel)return;
 if(!s||!id){panel.hidden=true;stop();tl=null;loadedFor='';return}
 const ready=['complete','failed','cancelled','review'].includes(s.status)||['direction','render'].includes(s.stage);
 if(!ready){panel.hidden=true;return}
 if(!ui.canvas)build();
 const key=id+'|'+s.status+'|'+(s.action||'')+'|'+(s.queued_actions?.length||0);
 const changed=loadedFor!==id||key!==lastStatus||(s.video||'')!==lastVideo;
 if(!changed||loading)return;
 lastStatus=key;lastVideo=s.video||'';
 if(tl&&tl.job===id&&tl.dirty)refreshMeta(id);else load(false,id);
};

async function load(force,id=jobId){
 if(!id)return;loading=true;
 try{
  const data=await api(`/api/jobs/${id}/timeline`);
  if(id!==jobId)return;
  const same=tl&&tl.job===id;
  if(!same)stop();
  const colors=read(COLOR_KEY,{}),hidden=read(HIDDEN_KEY,[]);
  tl={job:id,duration:data.duration,editable:data.editable,status:data.status,hasVideo:data.has_video,serverDirty:data.timeline_dirty,
   lines:data.lines.map(l=>l.words.map(w=>({text:w.text,start:+w.start,end:+w.end}))),
   art:data.art.map(a=>({start:+a.start,def:+a.default_start,url:a.url,lyrics:a.lyrics,img:null})),
   stems:data.stems.map(s=>({id:s.id,url:s.url,color:colors[s.id]||STEMS[s.id]?.[1]||'#ccc',hidden:hidden.includes(s.id),wave:null})),
   zoom:same?tl.zoom:read(ZOOM_KEY,110),sel:same?tl.sel:null,hover:null,drag:null,undo:[],redo:[],dirty:false};
  tl.art.forEach(a=>{if(a.url){a.img=new Image();a.img.onload=draw;a.img.src=a.url}});
  loadedFor=id;$('timelinePanel').hidden=false;
  labels();sources();setZoom(tl.zoom,null);status();inspector();resize();
  if(!same){const first=Math.min(tl.lines[0]?.[0]?.start??0,tl.art[0]?.start??Infinity);ui.scroller.scrollLeft=Math.max(0,(first-1)*tl.zoom)}
  draw();nowPlaying(true);
  tl.stems.forEach(s=>api(`/api/jobs/${id}/waveform/${s.id}`).then(w=>{if(tl?.job===id){s.wave=w;draw()}}).catch(()=>{s.failed=true;draw()}));
 }catch(e){if(id===jobId){$('timelinePanel').hidden=true;loadedFor=id}}
 finally{loading=false}
}

async function refreshMeta(id){
 try{const data=await api(`/api/jobs/${id}/timeline`);if(tl?.job!==id)return;tl.editable=data.editable;tl.status=data.status;tl.hasVideo=data.has_video;
  data.art.forEach((a,i)=>{const art=tl.art[i];if(art&&a.url&&a.url!==art.url){art.url=a.url;art.img=new Image();art.img.onload=draw;art.img.src=a.url}});status()}catch{}
}

function sources(){
 ui.listen.replaceChildren(...tl.stems.filter(s=>s.url).map(s=>new Option(STEMS[s.id]?.[0]||s.id,s.id)));
 if(tl.stems.some(s=>s.id==='mix'))ui.listen.value='mix';
 setSource(ui.listen.value);
}
function setSource(id){
 const stem=tl.stems.find(s=>s.id===id);if(!stem?.url)return;
 const at=ui.audio.currentTime||0,playing=!ui.audio.paused;
 if(ui.audio.dataset.src===stem.url)return;
 ui.audio.dataset.src=stem.url;ui.audio.src=stem.url;
 ui.audio.addEventListener('loadedmetadata',()=>{ui.audio.currentTime=Math.min(at,tl.duration);if(playing)ui.audio.play().catch(()=>{})},{once:true});
 draw();labels();
}
function stop(){if(ui.audio){ui.audio.pause()}if(ui.editor)ui.editor.hidden=true}

/* ---------- lane headers ---------- */
function lanes(){
 const out=[{id:'ruler',h:H.ruler}];
 if(tl.art.length)out.push({id:'art',h:H.art});
 out.push({id:'line',h:H.line},{id:'word',h:H.word});
 for(const s of tl.stems)if(!s.hidden)out.push({id:'stem',stem:s,h:H.stem});
 let y=0;for(const l of out){l.y=y;y+=l.h}
 return out;
}
function labels(){
 ui.labels.replaceChildren();
 for(const lane of lanes()){
  const row=el('div','tl-label tl-label-'+lane.id);row.style.height=lane.h+'px';
  if(lane.id==='ruler'){row.append(el('span','tl-label-muted','Time'))}
  else if(lane.id==='art')row.append(el('strong',null,'Images'));
  else if(lane.id==='line')row.append(el('strong',null,'Lines'));
  else if(lane.id==='word')row.append(el('strong',null,'Words'));
  else{
   const s=lane.stem;const swatch=el('input','tl-swatch');swatch.type='color';swatch.value=s.color;swatch.title='Change '+(STEMS[s.id]?.[0]||s.id)+' colour';swatch.setAttribute('aria-label',swatch.title);
   swatch.oninput=()=>{s.color=swatch.value;const c=read(COLOR_KEY,{});c[s.id]=s.color;write(COLOR_KEY,c);draw()};
   const name=el('span','tl-stem-name',STEMS[s.id]?.[0]||s.id);
   const solo=button('🎧',()=>{ui.listen.value=s.id;setSource(s.id)});solo.className='tl-mini'+(ui.listen.value===s.id?' on':'');solo.title='Listen to '+name.textContent;solo.setAttribute('aria-label',solo.title);
   const hide=button('×',()=>{s.hidden=true;write(HIDDEN_KEY,tl.stems.filter(x=>x.hidden).map(x=>x.id));labels();resize();draw()});hide.className='tl-mini';hide.title='Hide this lane';hide.setAttribute('aria-label','Hide '+name.textContent+' lane');
   row.append(swatch,name,solo,hide);
  }
  ui.labels.append(row);
 }
 const hidden=tl.stems.filter(s=>s.hidden);
 if(hidden.length){const row=el('div','tl-label tl-label-more');const show=button('Show '+hidden.length+' hidden',()=>{tl.stems.forEach(s=>s.hidden=false);write(HIDDEN_KEY,[]);labels();resize();draw()});show.className='tl-mini tl-show';row.append(show);ui.labels.append(row)}
}

/* ---------- geometry ---------- */
const zoomFromSlider=v=>8*Math.pow(400/8,v/100);
const sliderFromZoom=z=>Math.round(100*Math.log(z/8)/Math.log(400/8));
function viewStart(){return ui.scroller.scrollLeft/tl.zoom}
function viewCenter(){return viewStart()+ui.scroller.clientWidth/2/tl.zoom}
const X=t=>(t-viewStart())*tl.zoom,T=x=>x/tl.zoom+viewStart();
function setZoom(z,anchor){
 const fit=Math.max(4,(ui.scroller.clientWidth-2)/Math.max(1,tl.duration));
 z=clamp(z,Math.min(8,fit),400);const keep=anchor===null?null:(anchor-viewStart())*tl.zoom;
 tl.zoom=z;write(ZOOM_KEY,z);ui.zoom.value=sliderFromZoom(z);resize();
 if(keep!==null)ui.scroller.scrollLeft=anchor*z-keep;
 draw();
}
function resize(){
 if(!tl)return;const w=ui.scroller.clientWidth,hgt=lanes().reduce((a,l)=>a+l.h,0),r=devicePixelRatio||1;
 ui.track.style.width=Math.max(w,Math.ceil(tl.duration*tl.zoom))+'px';ui.track.style.height=hgt+'px';
 ui.canvas.style.width=w+'px';ui.canvas.style.height=hgt+'px';
 if(ui.canvas.width!==Math.round(w*r)||ui.canvas.height!==Math.round(hgt*r)){ui.canvas.width=Math.round(w*r);ui.canvas.height=Math.round(hgt*r)}
}
const flat=()=>tl.lines.flatMap((words,li)=>words.map((w,wi)=>({w,li,wi})));

/* ---------- drawing ---------- */
let queued=false;
function draw(){if(!queued&&tl){queued=true;requestAnimationFrame(()=>{queued=false;paint()})}}
function fit(ctx,text,width){if(ctx.measureText(text).width<=width)return text;let lo=0,hi=text.length;while(lo<hi){const m=(lo+hi+1)>>1;ctx.measureText(text.slice(0,m)+'…').width<=width?lo=m:hi=m-1}return lo?text.slice(0,lo)+'…':''}
function rounded(ctx,x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.roundRect?ctx.roundRect(x,y,w,h,r):ctx.rect(x,y,w,h)}
function paint(){
 if(!tl||!ui.canvas.width)return;
 const ctx=ui.canvas.getContext('2d'),r=devicePixelRatio||1,W=ui.canvas.width/r,Hh=ui.canvas.height/r;
 ctx.setTransform(r,0,0,r,0,0);ctx.clearRect(0,0,W,Hh);
 const L=lanes(),t0=viewStart(),t1=t0+W/tl.zoom,now=ui.audio.currentTime||0;
 L.forEach((lane,i)=>{ctx.fillStyle=i%2?'#ffffff05':'#ffffff02';ctx.fillRect(0,lane.y,W,lane.h);ctx.fillStyle='#ffffff10';ctx.fillRect(0,lane.y+lane.h-1,W,1)});
 const step=[.05,.1,.25,.5,1,2,5,10,15,30,60,120].find(s=>s*tl.zoom>=70)||120,minor=step/5;
 ctx.font='11px Inter,"Segoe UI",sans-serif';ctx.textBaseline='middle';
 for(let t=Math.floor(t0/minor)*minor;t<=t1;t+=minor){
  const x=Math.round(X(t))+.5,major=Math.abs(t/step-Math.round(t/step))<1e-6;
  ctx.fillStyle=major?'#ffffff16':'#ffffff08';ctx.fillRect(x,major?0:H.ruler-7,1,major?Hh:7);
  if(major){ctx.fillStyle='#c9d4ec';ctx.fillText(step<1?clock(t).replace(/^00:/,''):clock(t).slice(0,5),x+(x<10?10:5),H.ruler/2+1)}
 }
 ctx.fillStyle='#00000055';ctx.fillRect(X(tl.duration),0,W,Hh);
 const sel=tl.sel;let guides=null;
 for(const lane of L){
  if(lane.id==='art')paintArt(ctx,lane,t0,t1,now);
  if(lane.id==='line')paintLines(ctx,lane,t0,t1,now);
  if(lane.id==='word')guides=paintWords(ctx,lane,t0,t1,now);
  if(lane.id==='stem')paintStem(ctx,lane,W,t0);
 }
 if(guides){ctx.save();ctx.setLineDash([3,4]);ctx.strokeStyle='#ffffffa0';ctx.lineWidth=1;for(const t of guides){const x=Math.round(X(t))+.5;ctx.beginPath();ctx.moveTo(x,H.ruler);ctx.lineTo(x,Hh);ctx.stroke()}ctx.restore()}
 if(tl.snapAt!=null){const x=Math.round(X(tl.snapAt))+.5;ctx.fillStyle='#ffe28a';ctx.fillRect(x-.5,0,2,Hh)}
 const px=Math.round(X(now))+.5;
 if(px>=-2&&px<=W+2){ctx.fillStyle='#ff6b8b';ctx.fillRect(px-.5,0,2,Hh);ctx.beginPath();ctx.moveTo(px-6,0);ctx.lineTo(px+7,0);ctx.lineTo(px+.5,9);ctx.closePath();ctx.fill()}
 if(tl.drag?.moved&&tl.drag.readout)bubble(ctx,W,L);
 paintMap();
}
function bubble(ctx,W,L){
 const d=tl.drag,{time,delta}=d.readout,lane=L.find(l=>l.id===(d.kind==='art'?'art':d.kind==='line'?'line':'word'));
 const text=time.toFixed(3)+' s',sub=(delta>=0?'+':'−')+Math.abs(delta*1000).toFixed(0)+' ms'+(d.ripple?' · moving everything after':'');
 ctx.font='600 12px Inter,"Segoe UI",sans-serif';const w1=ctx.measureText(text).width;ctx.font='11px Inter,"Segoe UI",sans-serif';const w2=ctx.measureText(sub).width;
 const bw=Math.max(w1,w2)+20,bh=38,x=clamp(X(time)-bw/2,4,W-bw-4),y=Math.max(2,lane.y-bh-4);
 ctx.save();ctx.shadowColor='#0009';ctx.shadowBlur=14;rounded(ctx,x,y,bw,bh,9);ctx.fillStyle='#0d1526f2';ctx.fill();ctx.restore();
 rounded(ctx,x+.5,y+.5,bw-1,bh-1,9);ctx.strokeStyle='#ffffff40';ctx.stroke();
 ctx.fillStyle='#ffffff';ctx.font='600 12px Inter,"Segoe UI",sans-serif';ctx.fillText(text,x+10,y+13);ctx.fillStyle=delta?'#ffd28f':'#9fb0cc';ctx.font='11px Inter,"Segoe UI",sans-serif';ctx.fillText(sub,x+10,y+28);
}
function mapTo(e){if(!tl)return;const r=ui.map.getBoundingClientRect(),t=clamp((e.clientX-r.left)/r.width,0,1)*tl.duration;ui.scroller.scrollLeft=Math.max(0,t*tl.zoom-ui.scroller.clientWidth/2)}
function paintMap(){
 const c=ui.map,r=devicePixelRatio||1,W=c.clientWidth,Hh=c.clientHeight;if(!W)return;
 if(c.width!==Math.round(W*r)||c.height!==Math.round(Hh*r)){c.width=Math.round(W*r);c.height=Math.round(Hh*r)}
 const ctx=c.getContext('2d');ctx.setTransform(r,0,0,r,0,0);ctx.clearRect(0,0,W,Hh);const k=W/tl.duration;
 tl.art.forEach((a,i)=>{const e=i+1<tl.art.length?tl.art[i+1].start:tl.duration;ctx.fillStyle=i%2?'#9fb7ff12':'#9fb7ff22';ctx.fillRect(a.start*k,0,(e-a.start)*k,Hh);ctx.fillStyle='#bccbffaa';ctx.fillRect(a.start*k,0,1.5,Hh)});
 const stem=tl.stems.find(s=>s.id==='vocals'&&s.wave)||tl.stems.find(s=>s.wave);
 if(stem){const {rate,rms}=stem.wave,mid=Hh*.62,amp=Hh*.32;ctx.beginPath();ctx.moveTo(0,mid);const top=[];for(let x=0;x<W;x++){const a=Math.floor(x/k*rate),b=Math.max(a+1,Math.floor((x+1)/k*rate));let m=0;for(let i=a;i<Math.min(rms.length,b);i++)if(rms[i]>m)m=rms[i];top.push(Math.pow(m/255,.8)*amp)}
  top.forEach((v,x)=>ctx.lineTo(x,mid-v));for(let x=top.length-1;x>=0;x--)ctx.lineTo(x,mid+top[x]);ctx.closePath();ctx.fillStyle=stem.color+'55';ctx.fill();ctx.strokeStyle=stem.color+'99';ctx.lineWidth=1;ctx.stroke()}
 tl.lines.forEach((words,li)=>{ctx.fillStyle=LINE_HUES[li%LINE_HUES.length]+'cc';ctx.fillRect(words[0].start*k,3,Math.max(2,(words.at(-1).end-words[0].start)*k),4)});
 const v0=viewStart()*k,vw=ui.scroller.clientWidth/tl.zoom*k;
 ctx.fillStyle='#00000066';ctx.fillRect(0,0,v0,Hh);ctx.fillRect(v0+vw,0,W,Hh);
 ctx.strokeStyle='#e6edff';ctx.lineWidth=1.5;rounded(ctx,v0+.75,.75,Math.max(4,vw-1.5),Hh-1.5,5);ctx.stroke();
 const px=(ui.audio.currentTime||0)*k;ctx.fillStyle='#ff6b8b';ctx.fillRect(px-.5,0,2,Hh);
}
function paintArt(ctx,lane,t0,t1,now){
 const y=lane.y+6,h=lane.h-12;
 tl.art.forEach((a,i)=>{
  const end=i+1<tl.art.length?tl.art[i+1].start:tl.duration;if(end<t0||a.start>t1)return;
  const x=X(a.start),w=Math.max(2,X(end)-x-2),selected=tl.sel?.kind==='art'&&tl.sel.ai===i,hover=tl.hover?.kind==='art'&&tl.hover.ai===i;
  ctx.save();rounded(ctx,x,y,w,h,9);ctx.fillStyle=selected?'#9fb7ff38':'#9fb7ff16';ctx.fill();ctx.clip();
  if(a.img?.complete&&a.img.naturalWidth){const nw=a.img.naturalWidth,nh=a.img.naturalHeight,sh=Math.min(nh,nw*h/w);ctx.globalAlpha=.22;ctx.filter='blur(6px) saturate(1.3)';ctx.drawImage(a.img,0,(nh-sh)/2,nw,sh,x,y-8,w,h+16);ctx.filter='none';ctx.globalAlpha=1;
   const g=ctx.createLinearGradient(x,0,x+w,0);g.addColorStop(0,'#0b122000');g.addColorStop(1,'#0b1220aa');ctx.fillStyle=g;ctx.fillRect(x,y,w,h);
   const ih=h-10,iw=ih*nw/nh;ctx.save();rounded(ctx,x+9,y+5,iw,ih,7);ctx.clip();ctx.drawImage(a.img,x+9,y+5,iw,ih);ctx.restore()}
  const label='Image '+(i+1);ctx.font='600 11px Inter,"Segoe UI",sans-serif';const tw=ctx.measureText(label).width;
  const lx=x+Math.min(w-tw-14,h*1.0+12);if(lx>x+4){ctx.fillStyle='#0b1220c0';rounded(ctx,lx-6,y+6,tw+12,18,9);ctx.fill();ctx.fillStyle='#eef3ff';ctx.fillText(label,lx,y+15)}
  ctx.restore();
  ctx.strokeStyle=selected?'#ffffff':hover?'#d8e3ff':'#9fb7ff70';ctx.lineWidth=selected?1.6:1;rounded(ctx,x+.5,y+.5,w-1,h-1,9);ctx.stroke();
  ctx.fillStyle=selected||hover?'#ffffff':'#bccbff';rounded(ctx,x,y,4,h,2);ctx.fill();
  if(Math.abs(a.start-a.def)>.0005){const dx=X(a.def);ctx.save();ctx.setLineDash([2,3]);ctx.strokeStyle='#ffffff60';ctx.beginPath();ctx.moveTo(dx+.5,y);ctx.lineTo(dx+.5,y+h);ctx.stroke();ctx.restore()}
 });
}
function paintLines(ctx,lane,t0,t1,now){
 const y=lane.y+5,h=lane.h-10;ctx.font='500 11px Inter,"Segoe UI",sans-serif';
 tl.lines.forEach((words,li)=>{
  const s=words[0].start,e=words.at(-1).end;if(e<t0||s>t1)return;
  const x=X(s),w=Math.max(3,X(e)-x),hue=LINE_HUES[li%LINE_HUES.length],selected=tl.sel?.kind==='line'&&tl.sel.li===li,active=now>=s&&now<e;
  rounded(ctx,x,y,w,h,h/2);ctx.fillStyle=hue+(selected?'66':active?'44':'26');ctx.fill();ctx.strokeStyle=selected?'#fff':hue+'99';ctx.lineWidth=selected?1.5:1;ctx.stroke();
  if(w>30){ctx.fillStyle='#eef3ff';ctx.fillText(fit(ctx,(li+1)+'  '+words.map(w=>w.text).join(' '),w-20),x+10,y+h/2+.5)}
 });
}
function paintWords(ctx,lane,t0,t1,now){
 const y=lane.y+6,h=lane.h-12;let guides=null;ctx.font='600 12px Inter,"Segoe UI",sans-serif';
 tl.lines.forEach((words,li)=>words.forEach((wd,wi)=>{
  if(wd.end<t0||wd.start>t1)return;
  const x=X(wd.start),w=Math.max(2,X(wd.end)-x-1),hue=LINE_HUES[li%LINE_HUES.length];
  const selected=tl.sel?.kind==='word'&&tl.sel.li===li&&tl.sel.wi===wi,lineSel=tl.sel?.kind==='line'&&tl.sel.li===li,hover=tl.hover?.kind==='word'&&tl.hover.li===li&&tl.hover.wi===wi,active=now>=wd.start&&now<wd.end;
  rounded(ctx,x,y,w,h,6);ctx.fillStyle=active?'#ffffffd8':selected?hue+'aa':hue+(hover||lineSel?'55':'33');ctx.fill();
  ctx.strokeStyle=selected?'#ffffff':hue+(hover?'ee':'88');ctx.lineWidth=selected?1.6:1;ctx.stroke();
  if(selected||hover){ctx.fillStyle=selected?'#fff':'#ffffffaa';for(const ex of [x,x+w-3])ctx.fillRect(ex+.5,y+h/2-7,2,14)}
  if(w>16){const text=fit(ctx,wd.text,w-10),tw=ctx.measureText(text).width;ctx.fillStyle=active?'#111a2c':'#f4f7ff';ctx.fillText(text,x+(w-tw)/2,y+h/2+.5)}
  if(selected)guides=[wd.start,wd.end];
 }));
 if(tl.sel?.kind==='line'){const words=tl.lines[tl.sel.li];guides=[words[0].start,words.at(-1).end]}
 if(tl.sel?.kind==='art')guides=[tl.art[tl.sel.ai].start];
 return guides;
}
function paintStem(ctx,lane,W,t0){
 const s=lane.stem,mid=lane.y+lane.h/2,amp=lane.h/2-6;
 ctx.fillStyle=s.color+'0a';ctx.fillRect(0,lane.y,W,lane.h-1);
 if(!s.wave){ctx.fillStyle='#ffffff60';ctx.font='11px Inter,"Segoe UI",sans-serif';ctx.fillText(s.failed?'Waveform unavailable':'Reading audio…',12,mid);return}
 const {rate,peak,rms}=s.wave;
 const shape=(values,scale)=>{ctx.beginPath();const pts=[];for(let x=0;x<=W;x++){const a=Math.floor((t0+x/tl.zoom)*rate),b=Math.max(a+1,Math.floor((t0+(x+1)/tl.zoom)*rate));if(a>=values.length)break;let m=0;for(let k=Math.max(0,a);k<Math.min(values.length,b);k++)if(values[k]>m)m=values[k];pts.push([x,Math.pow(m/255,.75)*amp*scale])}
  if(!pts.length)return;ctx.moveTo(pts[0][0],mid-pts[0][1]);for(const [x,v] of pts)ctx.lineTo(x,mid-v);for(let k=pts.length-1;k>=0;k--)ctx.lineTo(pts[k][0],mid+pts[k][1]);ctx.closePath()};
 if(s.id==='vocals')for(const {w} of flat()){const a=X(w.start),b=X(w.end);if(b<0||a>W)continue;ctx.fillStyle='#ffffff0c';ctx.fillRect(a,lane.y+3,b-a,lane.h-7)}
 shape(peak,.92);ctx.fillStyle=s.color+'1c';ctx.fill();
 shape(rms,.92);const g=ctx.createLinearGradient(0,mid-amp,0,mid+amp);g.addColorStop(0,s.color+'8c');g.addColorStop(.5,s.color+'26');g.addColorStop(1,s.color+'8c');ctx.fillStyle=g;ctx.fill();
 ctx.save();ctx.strokeStyle=s.color+'b3';ctx.lineWidth=1;ctx.shadowColor=s.color;ctx.shadowBlur=6;ctx.stroke();ctx.restore();
 ctx.fillStyle='#ffffff14';ctx.fillRect(0,mid,W,1);
}

/* ---------- now playing ---------- */
let nowKey='';
function nowPlaying(force){
 if(!tl)return;const t=ui.audio.currentTime||0;
 let li=tl.lines.findIndex(w=>t<w.at(-1).end+.35);if(li<0)li=tl.lines.length-1;
 const ai=tl.art.reduce((found,a,i)=>a.start<=t?i:found,-1);
 const words=tl.lines[li],wi=words.findIndex(w=>t>=w.start&&t<w.end);
 const key=li+'|'+wi+'|'+ai+'|'+words.filter(w=>t>=w.end).length;
 ui.clock.textContent=clock(t)+' / '+clock(tl.duration);
 if(key===nowKey&&!force)return;nowKey=key;
 ui.nowArt.replaceChildren();const art=tl.art[Math.max(0,ai)];if(art?.url&&ai>=0){const img=el('img');img.src=art.url;img.alt='Image '+(ai+1);ui.nowArt.append(img)}else ui.nowArt.append(el('span',null,'♪'));
 ui.nowLine.replaceChildren(...words.map((w,i)=>{const span=el('span',t>=w.end?'sung':i===wi?'singing':'',w.text);span.onclick=()=>{select({kind:'word',li,wi:i});seek(w.start)};return span}).flatMap((s,i)=>i?[document.createTextNode(' '),s]:[s]));
 const next=tl.lines[li+1];ui.nowNext.textContent=next?next.map(w=>w.text).join(' '):'';
}
function frame(){nowPlaying();follow();draw();if(!ui.audio.paused)requestAnimationFrame(frame)}
function follow(){if(!ui.follow.checked||ui.audio.paused||tl.drag)return;const x=X(ui.audio.currentTime),w=ui.scroller.clientWidth;if(x>w*.85||x<0)ui.scroller.scrollLeft=Math.max(0,ui.audio.currentTime*tl.zoom-w*.2)}
function togglePlay(){if(!tl)return;if(ui.audio.paused)ui.audio.play().catch(e=>toast('Audio could not play: '+e.message));else ui.audio.pause()}
function seek(t){ui.audio.currentTime=clamp(t,0,tl.duration);nowPlaying(true);draw()}

/* ---------- hit testing and dragging ---------- */
function hit(x,y){
 const lane=lanes().find(l=>y>=l.y&&y<l.y+l.h);if(!lane)return null;const t=T(x);
 if(lane.id==='art'){for(let i=tl.art.length-1;i>=0;i--){const a=tl.art[i];if(x>=X(a.start)-EDGE&&t<(i+1<tl.art.length?tl.art[i+1].start:tl.duration))return{kind:'art',ai:i,lane}}return{kind:'seek',lane}}
 if(lane.id==='line'){const li=tl.lines.findIndex(w=>t>=w[0].start&&t<=w.at(-1).end);return li>=0?{kind:'line',li,lane}:{kind:'seek',lane}}
 if(lane.id==='word'){
  for(const {w,li,wi} of flat()){const a=X(w.start),b=X(w.end);if(x>=a-EDGE&&x<=b+EDGE){
   const edge=b-a>EDGE*3?(x<a+EDGE?'start':x>b-EDGE?'end':null):(x<a+2?'start':x>b-2?'end':null);
   if(x>=a-EDGE&&x<=b+EDGE&&(x>=a&&x<=b||edge))return{kind:'word',li,wi,edge,lane}}}
  return{kind:'seek',lane};
 }
 return{kind:'seek',lane};
}
function pos(e){const r=ui.canvas.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top]}
function snapshot(){return JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)})}
function restore(s){const v=JSON.parse(s);tl.lines=v.l;v.a.forEach((t,i)=>tl.art[i].start=t)}
function pointerDown(e){
 if(!tl||e.button!==0)return;ui.canvas.focus();commitEdit();const [x,y]=pos(e),h=hit(x,y);if(!h)return;
 ui.canvas.setPointerCapture(e.pointerId);
 if(h.kind==='seek'){select(null);tl.drag={kind:'seek'};seek(T(x));return}
 if(!tl.editable){select(h.kind==='word'?{kind:'word',li:h.li,wi:h.wi}:h.kind==='line'?{kind:'line',li:h.li}:{kind:'art',ai:h.ai});toast('The timeline is read-only while the video is being made.');return}
 select(h.kind==='word'?{kind:'word',li:h.li,wi:h.wi}:h.kind==='line'?{kind:'line',li:h.li}:{kind:'art',ai:h.ai});
 tl.drag={...h,x0:x,t0:T(x),before:snapshot(),orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)})),moved:false};
}
function pointerMove(e){
 if(!tl)return;const [x,y]=pos(e);const d=tl.drag;
 if(!d){const h=hit(x,y);tl.hover=h;ui.canvas.style.cursor=!h||h.kind==='seek'?'text':h.edge||h.kind==='art'&&Math.abs(x-X(tl.art[h.ai].start))<EDGE?'ew-resize':'grab';draw();return}
 if(d.kind==='seek'){seek(T(x));return}
 if(!d.moved&&Math.abs(x-d.x0)<3)return;d.moved=true;ui.canvas.style.cursor=d.edge?'ew-resize':'grabbing';
 let delta=(x-d.x0)/tl.zoom;const ripple=e.shiftKey,snap=!e.altKey;
 restore(JSON.stringify(d.orig));tl.snapAt=null;
 if(d.kind==='word')dragWord(d,delta,ripple,snap);
 if(d.kind==='line')dragLine(d,delta,ripple,snap);
 if(d.kind==='art')dragArt(d,delta,ripple,snap);
 d.ripple=ripple&&!d.edge;d.readout=readout(d);
 edgeScroll(x);inspector();draw();
}
function readout(d){
 if(d.kind==='art')return{time:tl.art[d.ai].start,delta:tl.art[d.ai].start-d.orig.a[d.ai]};
 const now=d.kind==='line'?tl.lines[d.li][0]:tl.lines[d.li][d.wi],was=d.kind==='line'?d.orig.l[d.li][0]:d.orig.l[d.li][d.wi];
 return d.edge==='end'?{time:now.end,delta:now.end-was.end}:{time:now.start,delta:now.start-was.start};
}
function pointerUp(e){
 if(!tl?.drag)return;const d=tl.drag;tl.drag=null;tl.snapAt=null;ui.canvas.style.cursor='';
 if(d.moved&&snapshot()!==d.before){tl.undo.push(d.before);tl.redo=[];markDirty()}
 draw();inspector();
}
function edgeScroll(x){const w=ui.scroller.clientWidth;if(x>w-30)ui.scroller.scrollLeft+=12;else if(x<30)ui.scroller.scrollLeft-=12}
function snapTo(t,targets,enabled){if(!enabled)return t;let best=null;for(const s of targets){if(Math.abs(X(s)-X(t))<=SNAP&&(best===null||Math.abs(s-t)<Math.abs(best-t)))best=s}if(best!==null){tl.snapAt=best;return best}return t}
function wordTargets(skip){const out=[ui.audio.currentTime||0];for(const {w} of flat())if(!skip.has(w)){out.push(w.start,w.end)}return out}
function shiftAfter(fromTime,delta,skipLi,skipWi){
 tl.lines.forEach((words,li)=>words.forEach((w,wi)=>{if((li>skipLi||li===skipLi&&wi>skipWi)){w.start+=delta;w.end+=delta}}));
 tl.art.forEach(a=>{if(a.start>=fromTime-1e-6)a.start+=delta});
}
function rippleRange(flatIndex){const all=flat(),after=all.slice(flatIndex);return{prev:all[flatIndex-1]?.w,maxEnd:Math.max(...after.map(o=>o.w.end))}}
function dragWord(d,delta,ripple,snap){
 const all=flat(),k=all.findIndex(o=>o.li===d.li&&o.wi===d.wi),w=all[k].w,prev=all[k-1]?.w,next=all[k+1]?.w;
 const floor=prev?Math.max(prev.start+GAP,Math.min(prev.end,w.start)):0,ceiling=next?Math.max(next.start,w.end):tl.duration;
 if(d.edge==='start'){let s=snapTo(w.start+delta,wordTargets(new Set([w])),snap);s=clamp(s,floor,w.end-MIN_WORD);w.start=round(s);return}
 if(d.edge==='end'){let t=snapTo(w.end+delta,wordTargets(new Set([w])),snap);t=clamp(t,w.start+MIN_WORD,Math.min(ceiling,tl.duration));w.end=round(t);return}
 if(ripple){
  const {maxEnd}=rippleRange(k);let s=snapTo(w.start+delta,wordTargets(new Set(all.slice(k).map(o=>o.w))),snap);delta=clamp(s-w.start,floor-w.start,tl.duration-maxEnd);
  const from=w.start;w.start=round(w.start+delta);w.end=round(w.end+delta);shiftAfter(from,delta,d.li,d.wi);roundAll();return;
 }
 const len=w.end-w.start;let s=w.start+delta;const se=snapTo(s+len,wordTargets(new Set([w])),snap);const ss=snapTo(s,wordTargets(new Set([w])),snap);
 s=tl.snapAt!==null&&ss!==s?ss:se!==s+len?se-len:s;
 s=clamp(s,floor,Math.max(floor,Math.min(ceiling,tl.duration)-len));w.start=round(s);w.end=round(s+len);
}
function dragLine(d,delta,ripple,snap){
 const words=tl.lines[d.li],all=flat(),k=all.findIndex(o=>o.li===d.li&&o.wi===0),prev=all[k-1]?.w,next=tl.lines[d.li+1]?.[0];
 const first=words[0],s=snapTo(first.start+delta,wordTargets(new Set(ripple?all.slice(k).map(o=>o.w):words)),snap);delta=s-first.start;
 const last=words.at(-1),lo=(prev?Math.max(prev.start+GAP,Math.min(prev.end,first.start)):0)-first.start;
 const hi=ripple?tl.duration-Math.max(...all.slice(k).map(o=>o.w.end)):Math.max(0,Math.min(next?Math.max(next.start,last.end)-last.end:Infinity,tl.duration-last.end));
 delta=clamp(delta,lo,hi);const from=first.start;words.forEach(w=>{w.start+=delta;w.end+=delta});
 if(ripple)shiftAfter(from,delta,d.li,words.length-1);roundAll();
}
function dragArt(d,delta,ripple,snap){
 const i=d.ai,a=tl.art[i],prev=tl.art[i-1],next=tl.art[i+1];
 const targets=[ui.audio.currentTime||0,...tl.lines.flatMap(l=>[l[0].start,l[0].start-1]),...tl.art.filter(x=>x!==a).map(x=>x.def)];
 let s=snapTo(a.start+delta,targets,snap);
 if(ripple){const dl=clamp(s-a.start,(prev?prev.start+ART_GAP:0)-a.start,tl.duration-ART_GAP-tl.art.at(-1).start);for(let j=i;j<tl.art.length;j++)tl.art[j].start=round(tl.art[j].start+dl);return}
 a.start=round(clamp(s,prev?prev.start+ART_GAP:0,next?next.start-ART_GAP:tl.duration-ART_GAP));
}
const round=v=>Math.round(v*1000)/1000;
function roundAll(){tl.lines.forEach(l=>l.forEach(w=>{w.start=round(w.start);w.end=round(w.end)}));tl.art.forEach(a=>a.start=round(a.start))}

/* ---------- editing text ---------- */
function doubleClick(e){
 if(!tl)return;const [x,y]=pos(e),h=hit(x,y);
 if(h?.kind==='word')editWord(h.li,h.wi);
 else if(h?.kind==='line')editLine(h.li);
 else if(h?.kind==='art'){select({kind:'art',ai:h.ai});seek(tl.art[h.ai].start)}
}
function editWord(li,wi){
 if(!tl.editable)return;const w=tl.lines[li][wi],lane=lanes().find(l=>l.id==='word');
 select({kind:'word',li,wi});
 const ww=Math.max(150,X(w.end)-X(w.start)+24);openEditor(w.text,(X(w.start)+X(w.end))/2-ww/2+ui.scroller.scrollLeft,lane.y+2,ww,lane.h-4,value=>{
  value=value.trim().replace(/\s+/g,' ');if(!value||!/[\p{L}\p{N}]/u.test(value)){toast('A word needs at least one letter or digit.');return false}
  if(value===w.text)return true;const before=snapshot();w.text=value;tl.undo.push(before);tl.redo=[];markDirty();return true});
}
function editLine(li){
 if(!tl.editable)return;const words=tl.lines[li],lane=lanes().find(l=>l.id==='line');select({kind:'line',li});
 const x=X(words[0].start);
 openEditor(words.map(w=>w.text).join(' '),x+ui.scroller.scrollLeft,lane.y+2,Math.max(260,X(words.at(-1).end)-x),lane.h-4,value=>{
  const parts=value.trim().split(/\s+/).filter(Boolean);
  if(parts.length!==words.length){toast(`Line ${li+1} needs ${words.length} words so each keeps its timing (you typed ${parts.length}).`);return false}
  const before=snapshot();let changed=false;parts.forEach((p,i)=>{if(words[i].text!==p){words[i].text=p;changed=true}});if(changed){tl.undo.push(before);tl.redo=[];markDirty()}return true});
}
let editCommit=null;
function openEditor(value,left,top,width,height,commit){
 const ed=ui.editor;ed.value=value;ed.hidden=false;
 const maxLeft=ui.scroller.scrollLeft+ui.scroller.clientWidth-width-4;
 Object.assign(ed.style,{left:Math.max(ui.scroller.scrollLeft+4,Math.min(left,maxLeft))+'px',top:top+'px',width:width+'px',height:height+'px'});
 editCommit=commit;ed.focus();ed.select();
 ed.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(commitEdit())ui.canvas.focus()}if(e.key==='Escape'){editCommit=null;ed.hidden=true;ui.canvas.focus()}e.stopPropagation()};
 ed.onblur=()=>commitEdit();
}
function commitEdit(){if(!editCommit)return true;const ok=editCommit(ui.editor.value);if(ok){editCommit=null;ui.editor.hidden=true;nowPlaying(true);inspector();draw()}return ok}

/* ---------- selection, keyboard, inspector ---------- */
function select(s){tl.sel=s;inspector();draw()}
function nudge(delta,ripple){
 const s=tl.sel;if(!s||!tl.editable)return;const before=snapshot();const d={...s,orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)}))};
 if(s.kind==='word')dragWord(d,delta,ripple,false);if(s.kind==='line')dragLine(d,delta,ripple,false);if(s.kind==='art')dragArt(d,delta,ripple,false);
 if(snapshot()!==before){tl.undo.push(before);tl.redo=[];markDirty()}draw();inspector();
}
function keyDown(e){
 if(!tl)return;const k=e.key,mod=e.ctrlKey||e.metaKey;
 if(k===' '){e.preventDefault();togglePlay();return}
 if(mod&&k.toLowerCase()==='z'){e.preventDefault();e.shiftKey?redo():undo();return}
 if(mod&&k.toLowerCase()==='y'){e.preventDefault();redo();return}
 if(mod&&k.toLowerCase()==='s'){e.preventDefault();save(false);return}
 if(k==='ArrowLeft'||k==='ArrowRight'){e.preventDefault();if(!tl.sel){seek((ui.audio.currentTime||0)+(k==='ArrowLeft'?-1:1)*(e.shiftKey?5:1));return}nudge((k==='ArrowLeft'?-1:1)*(e.shiftKey?.1:.01),e.altKey);return}
 if(k==='Tab'&&tl.sel?.kind==='word'){e.preventDefault();const all=flat(),i=all.findIndex(o=>o.li===tl.sel.li&&o.wi===tl.sel.wi),n=all[clamp(i+(e.shiftKey?-1:1),0,all.length-1)];select({kind:'word',li:n.li,wi:n.wi});reveal(n.w.start);return}
 if(k==='Enter'&&tl.sel){e.preventDefault();if(tl.sel.kind==='word')editWord(tl.sel.li,tl.sel.wi);if(tl.sel.kind==='line')editLine(tl.sel.li);return}
 if(k==='Escape'){select(null);return}
 if((k==='t'||k==='T')&&tl.sel?.kind==='word'&&tl.editable){e.preventDefault();tap();return}
 if(k==='Home'){seek(0);ui.scroller.scrollLeft=0}
}
function tap(){
 const all=flat(),i=all.findIndex(o=>o.li===tl.sel.li&&o.wi===tl.sel.wi),w=all[i].w,t=ui.audio.currentTime||0;
 const before=snapshot();const d={kind:'word',li:tl.sel.li,wi:tl.sel.wi,orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)}))};
 dragWord(d,t-w.start,false,false);if(snapshot()!==before){tl.undo.push(before);tl.redo=[];markDirty()}
 const n=all[i+1];if(n)select({kind:'word',li:n.li,wi:n.wi});draw();
}
function reveal(t){const x=X(t),w=ui.scroller.clientWidth;if(x<40||x>w-40)ui.scroller.scrollLeft=Math.max(0,t*tl.zoom-w*.3)}
function wheel(e){if(!tl)return;if(e.ctrlKey||e.metaKey){e.preventDefault();const r=ui.scroller.getBoundingClientRect(),anchor=T(e.clientX-r.left);setZoom(tl.zoom*Math.exp(-e.deltaY*.0025),anchor)}else if(e.shiftKey&&Math.abs(e.deltaY)>Math.abs(e.deltaX)){e.preventDefault();ui.scroller.scrollLeft+=e.deltaY}}
function undo(){if(!tl?.undo.length)return;tl.redo.push(snapshot());restore(tl.undo.pop());markDirty(tl.undo.length>0||tl.dirtyBase);draw();inspector();nowPlaying(true)}
function redo(){if(!tl?.redo.length)return;tl.undo.push(snapshot());restore(tl.redo.pop());markDirty();draw();inspector();nowPlaying(true)}
function markDirty(v=true){tl.dirty=v;status()}
function status(){
 if(!ui.badge||!tl)return;
 ui.badge.textContent=!tl.editable?'Read only':tl.dirty?'Unsaved changes':tl.serverDirty&&tl.hasVideo?'Saved · video needs rebuild':'Saved';
 ui.badge.className='badge tl-badge'+(tl.dirty?' dirty':tl.serverDirty&&tl.hasVideo?' pending':'');
 ui.save.disabled=!tl.editable||!tl.dirty;ui.revert.disabled=!tl.dirty;ui.undo.disabled=!tl.undo.length;ui.redo.disabled=!tl.redo.length;
 ui.rebuild.disabled=!tl.editable||!tl.dirty&&!(tl.serverDirty&&tl.hasVideo);
 ui.rebuild.textContent=tl.dirty?'Save & rebuild video':'Rebuild video';
 ui.rebuild.title=tl.status==='complete'?'':'After saving, restart this project from step 5 to render with the new timing.';
}
function numberField(label,value,onchange,step=.01){const f=el('label','tl-field');f.append(el('span',null,label));const i=el('input');Object.assign(i,{type:'number',step:String(step),value:value.toFixed(3)});i.disabled=!tl.editable;i.onchange=()=>{const v=+i.value;if(Number.isFinite(v))onchange(v)};f.append(i);return f}
function group(...children){const g=el('div','tl-ins-group');g.append(...children);return g}
function hear(t){seek(t-.4);ui.audio.play().catch(()=>{})}
function inspector(){
 if(!ui.inspector||!tl)return;const s=tl.sel;ui.inspector.replaceChildren();
 if(!s){ui.inspector.append(el('span','tl-inspector-empty','Select a word, line or image to adjust it precisely. Click the ruler or a waveform to move the playhead.'));return}
 const apply=(fn)=>{const before=snapshot();fn();roundAll();if(snapshot()!==before){tl.undo.push(before);tl.redo=[];markDirty()}inspector();draw();nowPlaying(true)};
 const at=()=>ui.audio.currentTime||0;
 if(s.kind==='word'){
  const w=tl.lines[s.li][s.wi];ui.inspector.append(el('strong','tl-inspector-title',`Line ${s.li+1} · word ${s.wi+1}`));
  const f=el('label','tl-field tl-text');f.append(el('span',null,'Text'));const t=el('input');t.value=w.text;t.disabled=!tl.editable;t.onchange=()=>{const v=t.value.trim().replace(/\s+/g,' ');if(!/[\p{L}\p{N}]/u.test(v)){toast('A word needs at least one letter or digit.');t.value=w.text;return}apply(()=>w.text=v)};f.append(t);
  const move=(edge,v)=>{const d={kind:'word',li:s.li,wi:s.wi,edge,orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)}))};apply(()=>dragWord(d,v-(edge==='end'?w.end:w.start),false,false))};
  ui.inspector.append(group(f,numberField('Start',w.start,v=>move('start',v)),numberField('End',w.end,v=>move('end',v)),el('span','tl-meta',((w.end-w.start)*1000).toFixed(0)+' ms')),
   group(button('▶ Hear',()=>hear(w.start)),button('Start ← playhead',()=>move('start',at()),!tl.editable),button('End ← playhead',()=>move('end',at()),!tl.editable)));
 }
 if(s.kind==='line'){
  const words=tl.lines[s.li];ui.inspector.append(el('strong','tl-inspector-title',`Line ${s.li+1}`),el('span','tl-line-text',words.map(w=>w.text).join(' ')));
  const shift=v=>{const d={kind:'line',li:s.li,orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)}))};apply(()=>dragLine(d,v-words[0].start,false,false))};
  ui.inspector.append(group(numberField('Starts at',words[0].start,shift)),group(button('▶ Hear',()=>hear(words[0].start)),button('Edit text',()=>editLine(s.li),!tl.editable),button('Start ← playhead',()=>shift(at()),!tl.editable)));
 }
 if(s.kind==='art'){
  const a=tl.art[s.ai];const head=el('div','tl-art-pick');if(a.url){const img=el('img');img.src=a.url;img.alt='';head.append(img)}head.append(el('strong','tl-inspector-title','Image '+(s.ai+1)));ui.inspector.append(head);
  if(a.lyrics)ui.inspector.append(el('span','tl-line-text',a.lyrics));
  const move=v=>{const d={kind:'art',ai:s.ai,orig:JSON.parse(JSON.stringify({l:tl.lines,a:tl.art.map(a=>a.start)}))};apply(()=>dragArt(d,v-a.start,false,false))};
  ui.inspector.append(group(numberField('Appears at',a.start,move)),group(button('▶ Hear',()=>hear(a.start)),button('Start ← playhead',()=>move(at()),!tl.editable),button('Reset to lyric timing',()=>move(a.def),!tl.editable||Math.abs(a.start-a.def)<.0005),
   button('Reset all images',()=>apply(()=>tl.art.forEach(x=>x.start=x.def)),!tl.editable||tl.art.every(x=>Math.abs(x.start-x.def)<.0005))));
 }
}

/* ---------- saving ---------- */
async function save(rebuild){
 if(!tl||!commitEdit())return;const id=tl.job;
 try{
  if(tl.dirty){
   const custom=tl.art.some(a=>Math.abs(a.start-a.def)>.0005);
   await api(`/api/jobs/${id}/timeline`,{lines:tl.lines.map(l=>l.map(w=>({text:w.text,start:w.start,end:w.end}))),art_starts:custom?tl.art.map(a=>a.start):null});
   tl.dirty=false;tl.serverDirty=true;tl.undo=[];tl.redo=[];status();
  }
  if(!rebuild){toast(tl.hasVideo?'Timeline saved. Rebuild the video to see the changes.':'Timeline saved.');return}
  if(tl.status!=='complete'){toast('Timeline saved. Restart this project from step 5 (Render) to use the new timing.');return}
  await api(`/api/jobs/${id}/rerender`,{});toast('Timeline saved. Rebuilding the video with the new timing…');
  loadedFor='';if(typeof poll==='function')poll();
 }catch(e){toast('Could not save the timeline: '+e.message)}
}
})();
