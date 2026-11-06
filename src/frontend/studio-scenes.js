// Scene metadata, tag filters and renderer-backed controls. Overrides live inside kinetic for profiles/history.
let sceneFilterTag = 'all';
let sceneFilterText = '';

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
  const inherited=['pan_speed','backdrop_rate','geometry'].includes(key)?settings[key]:undefined;
  input.value=own[key]??inherited??input.dataset.default;
  const out=input.parentElement.querySelector('output');if(out)out.value=input.value;
  input.setCustomValidity('');
 });
 document.querySelectorAll('.scene-config').forEach(panel=>{
  const custom=Object.keys(all[panel.dataset.scene]||{}).length>0;
  panel.querySelector('summary').textContent=custom?'Configure · customized':'Configure';
  panel.querySelector('button').disabled=!custom;
 });
 window.refreshSceneSamples?.();
}
function filterSceneCards(){
 let shown=0;
 document.querySelectorAll('.scene-choice').forEach(card=>{
  const tag=sceneFilterTag==='all'||card.dataset.tags.split(' ').includes(sceneFilterTag);
  const text=card.dataset.search.includes(sceneFilterText.toLowerCase().trim());
  card.hidden=!(tag&&text);if(!card.hidden)shown++;
 });
 const count=document.getElementById('sceneFilterCount');if(count)count.textContent=`${shown} scenes shown. Filtering keeps your selections.`;
}
function renderSceneEffects(scenes){
 const group=document.getElementById('sceneEffects');if(!group||!Array.isArray(scenes))return;
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
  const card=document.createElement('div');card.className='scene-choice';card.dataset.tags=(scene.tags||[]).join(' ');card.dataset.search=(scene.name+' '+scene.description+' '+card.dataset.tags).toLowerCase();
  const label=document.createElement('label');label.className='check-toggle';
  const box=document.createElement('input');box.type='checkbox';box.value=scene.id;box.dataset.kineticList='scenes';
  box.addEventListener('input',()=>{if(!group.querySelector('[data-kinetic-list="scenes"]:checked'))box.checked=true;storeKineticControls()});label.append(box,scene.name);
  const tags=document.createElement('div');tags.className='scene-tags';
  for(const tag of scene.tags||[]){const badge=document.createElement('span');badge.textContent=tag==='3d'?'3D':tag;tags.append(badge)}
  const sample=document.createElement('img');sample.className='scene-thumbnail';sample.loading='lazy';sample.alt=scene.name+' animated sample';sample.dataset.scene=scene.id;sample.src=sceneSampleQuery(scene.id);
  const description=document.createElement('p');description.className='scene-description';description.textContent=scene.description;
  const uses=document.createElement('div');uses.className='scene-uses';
  for(const [title,body] of [['Entry',scene.entry],['Exit',scene.exit]]){
   const row=document.createElement('p'),heading=document.createElement('strong');heading.textContent=title+': ';row.append(heading,body||'');uses.append(row);
  }
  const note=document.createElement('p');note.textContent=scene.selection;uses.append(note);
  const panel=document.createElement('details');panel.className='scene-config';panel.dataset.scene=scene.id;
  const summary=document.createElement('summary');summary.textContent='Configure';panel.append(summary);
  const controls=document.createElement('div');controls.className='scene-config-fields';
  for(const spec of scene.controls||[]){
   const field=document.createElement('label');field.append(spec.label);
   const input=document.createElement(spec.type==='select'?'select':'input');input.dataset.sceneId=scene.id;input.dataset.sceneSetting=spec.key;input.dataset.default=String(spec.default);
   input.setAttribute('aria-label',scene.name+': '+spec.label);
   if(spec.type==='select'){
    for(const value of spec.options){const option=document.createElement('option');option.value=value;option.textContent=value==='auto'?'Vary by line':value[0].toUpperCase()+value.slice(1);input.append(option)}
   }
   else if(spec.type==='color'){input.type='text';input.placeholder='Automatic · #RRGGBB';input.maxLength=7;input.pattern='#[0-9a-fA-F]{6}';}
   else{input.type='range';input.min=spec.min;input.max=spec.max;input.step=spec.step;const out=document.createElement('output');field.append(out);input.addEventListener('input',()=>out.value=input.value)}
   input.addEventListener('change',()=>{
    if(spec.type==='color'&&input.value&&!/^#[0-9a-fA-F]{6}$/.test(input.value)){input.setCustomValidity('Use #RRGGBB or leave blank for automatic.');input.reportValidity();return}
    input.setCustomValidity('');saveSceneOverride(scene.id,spec.key,spec.type==='range'?+input.value:input.value);
   });field.append(input);controls.append(field);
  }
  const reset=document.createElement('button');reset.type='button';reset.textContent='Reset this scene';reset.addEventListener('click',()=>saveSceneOverride(scene.id,null));controls.append(reset);panel.append(controls);
  card.append(label,tags,sample,description,uses,panel);return card;
 }));
 syncKineticControls();filterSceneCards();
}
window.renderSceneEffects=renderSceneEffects;
window.syncSceneControls=syncSceneControls;
