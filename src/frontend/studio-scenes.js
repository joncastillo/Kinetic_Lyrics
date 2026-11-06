// Scene metadata, tag filters and renderer-backed controls. Overrides live inside kinetic for profiles/history.
let sceneFilterTag = 'all';
let sceneFilterText = '';
let scenePreviewBackgrounds=[{id:'midnight',name:'Midnight studio',mode:'dark'}];
const sceneBackgrounds={},sceneFamilyActive={},sceneSampleTimers=new WeakMap();
function scenePreviewBackground(id){
 const allowed=scenePreviewBackgrounds.map(b=>b.id);
 if(!allowed.includes(sceneBackgrounds[id])){
  let saved;try{saved=sessionStorage.getItem('scenePreviewBackground:'+id)}catch{}
  const dark=scenePreviewBackgrounds.filter(b=>b.mode==='dark');
  sceneBackgrounds[id]=allowed.includes(saved)?saved:(dark[Math.floor(Math.random()*dark.length)]||scenePreviewBackgrounds[0]).id;
 }
 return sceneBackgrounds[id];
}
function queueSceneSample(img,src){
 if(img.dataset.requestedSrc===src)return;
 clearTimeout(sceneSampleTimers.get(img));img.dataset.requestedSrc=src;
 const card=img.closest('.scene-choice'),status=card?.querySelector('.scene-preview-status');
 card?.setAttribute('aria-busy','true');if(status)status.textContent='Updating preview…';
 sceneSampleTimers.set(img,setTimeout(()=>{if(img.getAttribute('src')!==src)img.src=src;else if(img.complete)finishSceneSample(img,img.naturalWidth>0)},250));
}
function finishSceneSample(img,ok){
 if(img.getAttribute('src')!==img.dataset.requestedSrc)return;
 const card=img.closest('.scene-choice');card?.setAttribute('aria-busy','false');
 const status=card?.querySelector('.scene-preview-status');if(status)status.textContent=ok?'Preview updated':'Preview failed. Click to retry.';
}
function changeSceneBackground(id,delta){
 const index=scenePreviewBackgrounds.findIndex(b=>b.id===scenePreviewBackground(id));
 const chosen=scenePreviewBackgrounds[(index+delta+scenePreviewBackgrounds.length)%scenePreviewBackgrounds.length];
 sceneBackgrounds[id]=chosen.id;try{sessionStorage.setItem('scenePreviewBackground:'+id,chosen.id)}catch{}
 syncSceneBackground(id);window.refreshSceneSamples?.();
}
function syncSceneBackground(id){
 const chosen=scenePreviewBackgrounds.find(b=>b.id===scenePreviewBackground(id));
 const label=document.querySelector(`[data-scene-background="${id}"]`);if(label)label.textContent=chosen.name+' · '+chosen.mode;
}
function sceneColorPanel(scene,spec){
 const panel=document.createElement('div');panel.className='scene-color-panel';panel.dataset.sceneColor=scene.id;
 const title=document.createElement('span');title.textContent=spec.label;panel.append(title);
 const row=document.createElement('div');row.className='scene-color-row';
 const picker=document.createElement('input');picker.type='color';picker.className='scene-color-picker';picker.setAttribute('aria-label',scene.name+' color picker');
 picker.addEventListener('input',()=>saveSceneOverride(scene.id,spec.key,picker.value));
 const hex=document.createElement('input');hex.type='text';hex.placeholder='Automatic';hex.maxLength=7;hex.pattern='#[0-9a-fA-F]{6}';hex.dataset.sceneId=scene.id;hex.dataset.sceneSetting=spec.key;hex.dataset.default='';hex.setAttribute('aria-label',scene.name+' exact highlight color');
 hex.addEventListener('input',()=>{hex.setCustomValidity(hex.value&&!/^#[0-9a-fA-F]{6}$/.test(hex.value)?'Use #RRGGBB or leave blank.':'');if(hex.checkValidity())saveSceneOverride(scene.id,spec.key,hex.value.toLowerCase())});
 hex.addEventListener('change',()=>{if(!hex.checkValidity())hex.reportValidity()});
 row.append(picker,hex);panel.append(row);
 const palette=document.createElement('div');palette.className='scene-color-swatches';palette.setAttribute('role','group');palette.setAttribute('aria-label','Highlight color palette');
 for(const [name,color] of [['Pearl','#f4eede'],['Ink','#15202d'],['Amber','#db9764'],['Slate','#87a2bc'],['Sage','#bfc196'],['Teal','#63a69d'],['Rose','#c494a6'],['Lavender','#b5a6d8']]){
  const button=document.createElement('button');button.type='button';button.dataset.color=color;button.style.setProperty('--swatch',color);button.setAttribute('aria-label',name);button.title=name+' '+color;button.addEventListener('click',()=>saveSceneOverride(scene.id,spec.key,color));palette.append(button);
 }
 const automatic=document.createElement('button');automatic.type='button';automatic.className='scene-color-auto';automatic.textContent='Automatic';automatic.addEventListener('click',()=>saveSceneOverride(scene.id,spec.key,''));panel.append(palette,automatic);return panel;
}

function mountSceneFamilies(group,scenes){
 const families=new Map();
 for(const scene of scenes){const key=scene.family||'Scene effects';if(!families.has(key))families.set(key,[]);families.get(key).push(scene)}
 const cards=[...group.children];
 for(const [family,presets] of families){
  const section=document.createElement('section');section.className='scene-family';section.dataset.family=family;
  const title=document.createElement('h3');title.textContent=family;
  const enabled=document.createElement('small');enabled.className='scene-family-count';title.append(enabled);
  const label=document.createElement('label');label.className='scene-preset-label';label.append('Preset to edit');
  const select=document.createElement('select');select.setAttribute('aria-label',family+' preset');
  for(const preset of presets){const option=document.createElement('option');option.value=preset.id;option.dataset.label=preset.name;option.textContent=preset.name;select.append(option)}
  select.value=sceneFamilyActive[family]||presets[0].id;
  select.addEventListener('change',()=>{sceneFamilyActive[family]=select.value;filterSceneCards()});
  label.append(select);section.append(title,label);
  for(const preset of presets)section.append(cards.find(card=>card.dataset.scene===preset.id));
  group.append(section);
 }
}

function sceneOverrides(){return kineticSettings().scene_settings||{}}
function saveSceneOverride(id,key,value){
 const settings=kineticSettings(),all={...(settings.scene_settings||{})},own={...(all[id]||{})};
 if(key===null)delete all[id];
 else{own[key]=value;if(value===''||value==='auto')delete own[key];if(Object.keys(own).length)all[id]=own;else delete all[id]}
 settings.scene_settings=all;
 document.getElementById('kinetic').value=JSON.stringify(settings);
 storeKineticControls();
 syncSceneControls();
 document.getElementById('kinetic').dispatchEvent(new Event('change',{bubbles:true}));
}
function syncSceneControls(){
 const settings=kineticSettings(),all=settings.scene_settings||{};
 document.querySelectorAll('[data-scene-setting]').forEach(input=>{
  const key=input.dataset.sceneSetting,own=all[input.dataset.sceneId]||{};
  const inherited=input.dataset.inherit!=='false'&&['pan_speed','backdrop_rate','geometry'].includes(key)?settings[key]:undefined;
  input.value=own[key]??inherited??input.dataset.default;
  const out=input.parentElement.querySelector('output');if(out)out.value=input.value;
  input.setCustomValidity('');
 });
 document.querySelectorAll('.scene-config').forEach(panel=>{
  const custom=Object.keys(all[panel.dataset.scene]||{}).length>0;
  panel.querySelector('summary').textContent=custom?'Configure · customized':'Configure';
  panel.querySelector('[data-scene-reset]').disabled=!custom;
 });
 document.querySelectorAll('[data-scene-color]').forEach(panel=>{
  const value=all[panel.dataset.sceneColor]?.accent||'';panel.querySelector('[type=color]').value=value||'#f4eede';
  panel.querySelectorAll('[data-color]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.color===value)));
  panel.querySelector('.scene-color-auto').setAttribute('aria-pressed',String(!value));
 });
 document.querySelectorAll('.scene-family').forEach(family=>{
  const boxes=[...family.querySelectorAll('[data-kinetic-list="scenes"]')];
  family.querySelector('.scene-family-count').textContent=`${boxes.filter(b=>b.checked).length}/${boxes.length} enabled`;
  for(const option of family.querySelector('select').options)option.textContent=(boxes.some(b=>b.value===option.value&&b.checked)?'✓ ':'')+option.dataset.label;
 });
 window.refreshSceneSamples?.();
}
function filterSceneCards(){
 let shown=0,families=0;
 document.querySelectorAll('.scene-family').forEach(family=>{
  const cards=[...family.querySelectorAll('.scene-choice')],matches=[];
  cards.forEach(card=>{
  const tag=sceneFilterTag==='all'||card.dataset.tags.split(' ').includes(sceneFilterTag);
  const text=(card.dataset.search+' '+family.dataset.family.toLowerCase()).includes(sceneFilterText.toLowerCase().trim());
  card.dataset.matches=String(tag&&text);if(tag&&text)matches.push(card);
  });
  shown+=matches.length;family.hidden=!matches.length;if(matches.length)families++;
  const select=family.querySelector('select');
  for(const option of select.options)option.hidden=!matches.some(card=>card.dataset.scene===option.value);
  if(!matches.some(card=>card.dataset.scene===select.value))select.value=matches[0]?.dataset.scene||'';
  cards.forEach(card=>card.hidden=card.dataset.scene!==select.value||card.dataset.matches!=='true');
 });
 const count=document.getElementById('sceneFilterCount');if(count)count.textContent=`${shown} presets in ${families} families. Switch presets to compare; filtering keeps your selections.`;
}
function renderSceneEffects(scenes,backgrounds){
 const group=document.getElementById('sceneEffects');if(!group||!Array.isArray(scenes))return;
 if(Array.isArray(backgrounds)&&backgrounds.length)scenePreviewBackgrounds=backgrounds;
 group.classList.add('scene-choices');
 document.getElementById('sceneFilters')?.remove();
 const filters=document.createElement('div');filters.id='sceneFilters';filters.className='scene-filters';
 const search=document.createElement('input');search.type='search';search.placeholder='Search scenes';search.setAttribute('aria-label','Search scenes');search.value=sceneFilterText;
 search.addEventListener('input',()=>{sceneFilterText=search.value;filterSceneCards()});
 const select=document.createElement('select');select.setAttribute('aria-label','Filter scenes by tag');
 for(const tag of ['all',...new Set(scenes.flatMap(s=>s.tags||[]))]){
  const option=document.createElement('option');option.value=tag;option.textContent=tag==='all'?'All styles':tag==='3d'?'3D':tag[0].toUpperCase()+tag.slice(1);select.append(option);
 }
 select.value=sceneFilterTag;select.addEventListener('change',()=>{sceneFilterTag=select.value;filterSceneCards()});
 const count=document.createElement('small');count.id='sceneFilterCount';count.setAttribute('aria-live','polite');
 filters.append(search,select,count);group.before(filters);
 group.replaceChildren(...scenes.map(scene=>{
  const card=document.createElement('div');card.className='scene-choice';card.dataset.scene=scene.id;card.dataset.tags=(scene.tags||[]).join(' ');card.dataset.search=(scene.name+' '+scene.description+' '+card.dataset.tags).toLowerCase();
  const label=document.createElement('label');label.className='check-toggle';
  const box=document.createElement('input');box.type='checkbox';box.value=scene.id;box.dataset.kineticList='scenes';
  box.addEventListener('input',()=>{if(!group.querySelector('[data-kinetic-list="scenes"]:checked'))box.checked=true;storeKineticControls()});label.append(box,scene.name);
  const tags=document.createElement('div');tags.className='scene-tags';
  for(const tag of scene.tags||[]){const badge=document.createElement('span');badge.textContent=tag==='3d'?'3D':tag;tags.append(badge)}
  const sample=document.createElement('img');sample.className='scene-thumbnail';sample.loading='lazy';sample.alt=scene.name+' animated sample';sample.dataset.scene=scene.id;sample.src=sceneSampleQuery(scene.id);
  sample.dataset.requestedSrc=sample.getAttribute('src');sample.addEventListener('load',()=>finishSceneSample(sample,true));sample.addEventListener('error',()=>finishSceneSample(sample,false));
  const background=document.createElement('div');background.className='scene-background-picker';
  const backLabel=document.createElement('span');backLabel.dataset.sceneBackground=scene.id;backLabel.title='Preview background only; does not change the video';
  for(const [text,delta,title] of [['‹',-1,'Previous preview background'],['›',1,'Next preview background']]){
   const button=document.createElement('button');button.type='button';button.textContent=text;button.setAttribute('aria-label',scene.name+': '+title);button.addEventListener('click',()=>changeSceneBackground(scene.id,delta));background.append(button);
   if(delta===-1)background.append(backLabel);
  }
  const status=document.createElement('button');status.type='button';status.className='scene-preview-status';status.textContent='Loading preview…';status.setAttribute('aria-live','polite');status.addEventListener('click',()=>{sample.dataset.requestedSrc='';sample.removeAttribute('src');queueSceneSample(sample,sceneSampleQuery(scene.id))});
  const description=document.createElement('p');description.className='scene-description';description.textContent=scene.description;
  const uses=document.createElement('div');uses.className='scene-uses';
  for(const [title,body] of [['Entry',scene.entry],['Exit',scene.exit]]){
   const row=document.createElement('p'),heading=document.createElement('strong');heading.textContent=title+': ';row.append(heading,body||'');uses.append(row);
  }
  const note=document.createElement('p');note.textContent=scene.selection;uses.append(note);
  const panel=document.createElement('details');panel.className='scene-config';panel.dataset.scene=scene.id;
  sample.tabIndex=0;sample.setAttribute('role','button');sample.setAttribute('aria-label','Configure '+scene.name+' and enlarge preview');
  sample.addEventListener('click',()=>panel.open=!panel.open);
  sample.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();panel.open=!panel.open}});
  panel.addEventListener('toggle',()=>sample.setAttribute('aria-expanded',String(panel.open)));
  const summary=document.createElement('summary');summary.textContent='Configure';panel.append(summary);
  const controls=document.createElement('div');controls.className='scene-config-fields';
  for(const spec of scene.controls||[]){
   if(spec.type==='color'){controls.append(sceneColorPanel(scene,spec));continue}
   const field=document.createElement('label');field.append(spec.label);
   const input=document.createElement(spec.type==='select'?'select':'input');input.dataset.sceneId=scene.id;input.dataset.sceneSetting=spec.key;input.dataset.default=String(spec.default);input.dataset.inherit=String(spec.inherit!==false);
   input.setAttribute('aria-label',scene.name+': '+spec.label);
   if(spec.type==='select'){
    for(const value of spec.options){const option=document.createElement('option');option.value=value;option.textContent=spec.labels?.[value]||(value==='auto'?'Scene default':(value[0].toUpperCase()+value.slice(1)).replaceAll('-',' '));input.append(option)}
   }
   else if(spec.type==='color'){input.type='text';input.placeholder='Automatic · #RRGGBB';input.maxLength=7;input.pattern='#[0-9a-fA-F]{6}';}
   else{input.type='range';input.min=spec.min;input.max=spec.max;input.step=spec.step;const out=document.createElement('output');field.append(out);input.addEventListener('input',()=>{out.value=input.value;saveSceneOverride(scene.id,spec.key,+input.value)})}
   input.addEventListener('change',()=>{
    if(spec.type==='color'&&input.value&&!/^#[0-9a-fA-F]{6}$/.test(input.value)){input.setCustomValidity('Use #RRGGBB or leave blank for automatic.');input.reportValidity();return}
    input.setCustomValidity('');saveSceneOverride(scene.id,spec.key,spec.type==='range'?+input.value:input.value);
   });field.append(input);controls.append(field);
  }
  const reset=document.createElement('button');reset.type='button';reset.dataset.sceneReset='';reset.textContent='Reset this preset';reset.addEventListener('click',()=>saveSceneOverride(scene.id,null));controls.append(reset);panel.append(controls);
  const media=document.createElement('div');media.className='scene-media';media.append(sample,background,status);
  card.append(label,tags,media,description,uses,panel);return card;
 }));
 mountSceneFamilies(group,scenes);scenes.forEach(scene=>syncSceneBackground(scene.id));
 syncKineticControls();filterSceneCards();
}
window.renderSceneEffects=renderSceneEffects;
window.syncSceneControls=syncSceneControls;

window.scenePreviewBackground=scenePreviewBackground;
window.queueSceneSample=queueSceneSample;
