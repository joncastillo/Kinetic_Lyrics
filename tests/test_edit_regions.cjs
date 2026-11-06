const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(){this.children=[];this.style={};this.dataset={};this.attrs={}}
 setAttribute(k,v){this.attrs[k]=v}
 hasAttribute(k){return Object.hasOwn(this.attrs,k)}
 toggleAttribute(k,on){if(on)this.attrs[k]='';else delete this.attrs[k]}
 replaceChildren(...items){this.children=items}
 append(...items){this.children.push(...items)}
 getBoundingClientRect(){return {left:0,top:0,width:1000,height:1000}}
 setPointerCapture(){}
}
const context={window:{},document:{createElement:()=>new Element(),createElementNS:()=>new Element()},Image:class{},URL,location:{href:'http://localhost/'}};
vm.createContext(context);vm.runInContext(fs.readFileSync('src/frontend/studio-edit-regions.js','utf8'),context);
const overlay=new Element(),list=new Element(),drawButton=new Element(),moveButton=new Element(),clearButton=new Element(),sourceButton=new Element();
// SVG does not reflect the HTML hidden property; CSS reads the attribute.
overlay.setAttribute('hidden','');
let changed=0;const guide=context.window.createEditRegionGuide({overlay,list,drawButton,moveButton,clearButton,sourceButton,onChange:()=>changed++,onSource:url=>guide.showFor(url)});
guide.load([],'source.png','/source.png');guide.showFor('/source.png');
assert.equal(overlay.hasAttribute('hidden'),false,'The source overlay must be visible for pointer input');
assert.equal(overlay.children[0].attrs['pointer-events'],'all','An empty overlay needs a full-image pointer target');
const event=(x,y,dataset={})=>({button:0,clientX:x,clientY:y,target:{dataset},pointerId:1,preventDefault(){}});
function draw(x,y,w,h){drawButton.onclick();overlay.onpointerdown(event(x,y));overlay.onpointermove(event(x+w,y+h));overlay.onpointerup()}
draw(100,100,200,300);draw(600,200,200,200);assert.equal(guide.regions.length,2);
overlay.onpointerdown(event(150,150,{index:'0'}));overlay.onpointermove(event(250,250));overlay.onpointerup();assert(Math.abs(guide.regions[0].x-.2)<1e-9);
overlay.onpointerdown(event(400,500,{index:'0',corner:'se'}));overlay.onpointermove(event(900,900));overlay.onpointerup();assert(Math.abs(guide.regions[0].w-.7)<1e-9);
list.children[1].children[2].onclick();assert.equal(guide.regions.length,1);
guide.showFor('/history.png');assert.equal(overlay.hasAttribute('hidden'),true);sourceButton.onclick();assert.equal(overlay.hasAttribute('hidden'),false);
clearButton.onclick();assert.equal(guide.regions.length,0);assert(changed>=6);
console.log('Multi-region draw, move, resize, remove, clear and source switching passed.');
