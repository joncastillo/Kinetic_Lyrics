/* Normalized, numbered rectangles on one source image. The backend creates the guide sent to Qwen. */
window.createEditRegionGuide=function({overlay,list,drawButton,moveButton,clearButton,sourceButton,status,onChange,onSource}){
 const NS='http://www.w3.org/2000/svg',colours=['#ff375f','#00bfff','#ffcc00','#34c759','#bf5af2','#ff9500'];
 let regions=[],source='',url='',selected=-1,mode='move',drag=null,visible=false,base=new Image();
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 const notify=()=>onChange?.();
 const point=event=>{const b=overlay.getBoundingClientRect();return b.width&&b.height?{x:clamp((event.clientX-b.left)/b.width,0,1),y:clamp((event.clientY-b.top)/b.height,0,1)}:null};
 function element(tag,attrs){const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);return node}
 function paint(){
  overlay.replaceChildren();overlay.toggleAttribute('hidden',!visible);overlay.style.cursor=mode==='draw'?'crosshair':'default';
  overlay.append(element('rect',{x:0,y:0,width:1000,height:1000,fill:'transparent','pointer-events':'all','data-background':'true'}));
  if(status)status.textContent=!source?'Select a reference image first.':mode==='draw'?'Click and drag on the image to draw a rectangle.':regions.length?`${regions.length} region(s) selected. Drag a region to move it, or its corners to resize.`:'Choose Draw rectangle, then drag across the image.';
  drawButton.setAttribute('aria-pressed',String(mode==='draw'));moveButton.setAttribute('aria-pressed',String(mode==='move'));
  regions.forEach((r,i)=>{
   const rect=element('rect',{x:r.x*1000,y:r.y*1000,width:r.w*1000,height:r.h*1000,fill:'transparent',stroke:colours[i%colours.length],'stroke-width':i===selected?5:3,'data-index':i});overlay.append(rect);
   const label=element('text',{x:r.x*1000+6,y:r.y*1000+25,fill:colours[i%colours.length],'font-size':26,'font-weight':'bold','pointer-events':'none'});label.textContent=i+1;overlay.append(label);
   if(i===selected)for(const [corner,x,y] of [['nw',r.x,r.y],['ne',r.x+r.w,r.y],['sw',r.x,r.y+r.h],['se',r.x+r.w,r.y+r.h]]){
    const handle=element('rect',{x:x*1000-7,y:y*1000-7,width:14,height:14,fill:colours[i%colours.length],stroke:'#000','data-index':i,'data-corner':corner});handle.style.cursor=corner+'-resize';overlay.append(handle);
   }
  });
 }
 function entries(){
  list.replaceChildren(...regions.map((r,i)=>{
   const row=document.createElement('div');row.className='edit-region-row';
   const select=document.createElement('button');select.type='button';select.textContent='Region '+(i+1);select.style.borderColor=colours[i%colours.length];
   select.onclick=()=>{selected=i;mode='move';onSource?.(url,source);paint()};
   const instruction=document.createElement('input');instruction.placeholder='Change in this region (optional)';instruction.maxLength=600;instruction.value=r.instruction||'';instruction.setAttribute('aria-label','Region '+(i+1)+' instruction');instruction.oninput=()=>{r.instruction=instruction.value;notify()};
   const remove=document.createElement('button');remove.type='button';remove.textContent='Remove';remove.setAttribute('aria-label','Remove region '+(i+1));remove.onclick=()=>{regions.splice(i,1);selected=-1;paint();entries();notify()};
   row.append(select,instruction,remove);return row;
  }));
  clearButton.disabled=!regions.length;
 }
 overlay.setAttribute('viewBox','0 0 1000 1000');overlay.setAttribute('preserveAspectRatio','none');
 overlay.onpointerdown=event=>{
  if(event.button!==0||!source||!visible)return;
  const start=point(event),index=Number(event.target.dataset.index);if(!start)return;
  if(mode==='draw'){
   if(regions.length>=12)return;selected=regions.length;regions.push({x:start.x,y:start.y,w:0,h:0,instruction:''});drag={start,index:selected,kind:'draw'};
  }else if(Number.isInteger(index)&&regions[index]){selected=index;drag={start,index,kind:event.target.dataset.corner||'move',before:{...regions[index]}}}else{selected=-1;paint();return}
  overlay.setPointerCapture(event.pointerId);event.preventDefault();paint();
 };
 overlay.onpointermove=event=>{
  if(!drag)return;const p=point(event),r=regions[drag.index],b=drag.before;if(!p)return;
  if(drag.kind==='draw'){r.x=Math.min(p.x,drag.start.x);r.y=Math.min(p.y,drag.start.y);r.w=Math.abs(p.x-drag.start.x);r.h=Math.abs(p.y-drag.start.y)}
  else if(drag.kind==='move'){r.x=clamp(b.x+p.x-drag.start.x,0,1-b.w);r.y=clamp(b.y+p.y-drag.start.y,0,1-b.h)}
  else{const west=drag.kind.includes('w'),north=drag.kind.includes('n');const x=west?clamp(p.x,0,b.x+b.w-.004):b.x,y=north?clamp(p.y,0,b.y+b.h-.004):b.y;r.x=x;r.y=y;r.w=west?b.x+b.w-x:clamp(p.x-b.x,.004,1-b.x);r.h=north?b.y+b.h-y:clamp(p.y-b.y,.004,1-b.y)}
  paint();
 };
 const finish=()=>{if(!drag)return;const r=regions[drag.index];if(r.w<.004||r.h<.004)regions.splice(drag.index,1);drag=null;mode='move';paint();entries();notify()};
 overlay.onpointerup=finish;overlay.onpointercancel=finish;
 drawButton.onclick=()=>{if(!source)return;mode='draw';onSource?.(url,source);paint()};moveButton.onclick=()=>{mode='move';onSource?.(url,source);paint()};sourceButton.onclick=()=>onSource?.(url,source);
 clearButton.onclick=()=>{regions=[];selected=-1;paint();entries();notify()};
 base.onload=notify;
 return {
  load(value,name,imageUrl){regions=(value||[]).map(r=>({...r}));source=name||'';if(url!==(imageUrl||''))visible=false;url=imageUrl||'';selected=-1;drag=null;mode='move';base.src=url;drawButton.disabled=moveButton.disabled=sourceButton.disabled=!source;paint();entries();notify()},
  showFor(imageUrl){visible=!!url&&new URL(imageUrl,location.href).href===new URL(url,location.href).href;paint()},
  get regions(){return regions.map(r=>({...r}))},get source(){return source},
  thumbnail(){if(!regions.length||!base.complete||!base.naturalWidth)return '';const canvas=document.createElement('canvas');canvas.width=640;canvas.height=Math.round(640*base.naturalHeight/base.naturalWidth);const ctx=canvas.getContext('2d');ctx.drawImage(base,0,0,canvas.width,canvas.height);ctx.lineWidth=3;ctx.font='bold 18px sans-serif';regions.forEach((r,i)=>{ctx.strokeStyle=ctx.fillStyle=colours[i%colours.length];ctx.strokeRect(r.x*canvas.width,r.y*canvas.height,r.w*canvas.width,r.h*canvas.height);ctx.fillText(String(i+1),r.x*canvas.width+4,r.y*canvas.height+20)});return canvas.toDataURL('image/png')}
 };
};
