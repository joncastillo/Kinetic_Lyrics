const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(tag='div'){this.tag=tag;this.children=[];this.fields=new Map();this.events={};this.value='';this.disabled=false;this.hidden=false;}
 querySelector(key){if(!this.fields.has(key))this.fields.set(key,new Element(key));return this.fields.get(key)}
 append(...children){this.children.push(...children)}
 add(child){this.children.push(child)}
 replaceChildren(...children){this.children=children}
 setAttribute(name,value){this[name]=value}
 addEventListener(name,fn){this.events[name]=fn}
 showModal(){this.open=true}
 close(){this.open=false;this.events.close?.()}
 remove(){this.removed=true}
}
const body=new Element(),requests=[],toasts=[];
const context={window:{poll(){}},document:{body,createElement:tag=>new Element(tag)},jobId:'song',artworkRefsSignature:'old',
 Option:class {constructor(label,value){this.label=label;this.value=value}},toast:value=>toasts.push(value),
 api:async(path,payload)=>{requests.push({path,payload});return path.endsWith('reference-prompt')?
  {name:'Doctor',current_image:'/doctor.png',looks:'A blue coat.',prompt:'Draw the doctor. A blue coat. Same face.',revision:'r1',images:[1,2],dependents:['Doctor injured'],max_references:4,
   inputs:[{kind:'entity',id:'base',role:'identity'}],options:[{kind:'entity',id:'base',label:'Base',role:'identity',url:'/base.png'},{kind:'builtin',id:'default-style',label:'Art style',role:'style',url:'/style.jpg'}]}:
  {ok:true,message:'Saved and regenerating'};}};
vm.createContext(context);vm.runInContext(fs.readFileSync('src/frontend/studio-reference-regeneration.js','utf8'),context);
(async()=>{
 await context.window.openReferenceRegeneration({id:'doctor',name:'Doctor'});
 const dialog=body.children.at(-1),q=s=>dialog.querySelector(s);
 assert(dialog.open);
 assert.equal(q('.reference-current-preview img').src,'/doctor.png');
 assert.equal(q('.reference-current-preview img').hidden,false);
 assert.equal(q('.reference-description').value,'A blue coat.');
 q('.reference-description').value='A red coat.';q('.reference-description').oninput();
 assert(q('.reference-generation-prompt').value.includes('A red coat.'));
 assert(!q('.reference-generation-prompt').value.includes('A blue coat.'));
 const cards=q('.reference-input-grid').children;
 const checkbox=cards[1].children[0].children[0];checkbox.checked=true;checkbox.onchange();
 assert.equal(q('.reference-input-count').textContent,'2 / 4 selected');
 await q('form').onsubmit({preventDefault(){}});
 const submitted=requests.at(-1);
 assert(submitted.path.endsWith('/reference-repaint'));
 assert.equal(submitted.payload.looks,'A red coat.');
 assert.equal(submitted.payload.revision,'r1');
 assert.deepEqual(JSON.parse(JSON.stringify(submitted.payload.inputs)),[{kind:'entity',id:'base',role:'identity'},{kind:'builtin',id:'default-style',role:'style'}]);
 assert(dialog.removed&&toasts.length===1);
 const count=requests.length;
 await context.window.openReferenceRegeneration({id:'doctor',name:'Doctor'});
 body.children.at(-1).querySelector('.reference-cancel').onclick();
 assert.equal(requests.length,count+1,'Cancel must not save the edited recipe');
 console.log('Reference panel: description synchronization, input selection, persistence payload and Cancel passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
