// The prompts the vision model checks with (Artwork: images; References: reference pictures). Each box shows the
// project's own prompt, or the built-in one the server sends; a box left as the built-in one is saved as '' so a
// later change to the built-in prompt still reaches the project.
(()=>{
 const DEFAULTS={imageCheckPrompt:'',referenceCheckPrompt:''};
 const KEYS={imageCheckPrompt:'image_check_prompt',referenceCheckPrompt:'reference_check_prompt'};
 async function loadDefaults(){
  try{const cfg=await (await fetch('/api/config')).json();
   DEFAULTS.imageCheckPrompt=cfg.image_check_prompt||'';DEFAULTS.referenceCheckPrompt=cfg.reference_check_prompt||'';
   for(const id of Object.keys(DEFAULTS)){const box=document.getElementById(id);if(box&&!box.value.trim())box.value=DEFAULTS[id]}
  }catch{}
  syncResets();
 }
 // "Load default prompt" shows only while a box differs from the built-in prompt
 function syncResets(){
  for(const button of document.querySelectorAll('[data-reset-prompt]')){const box=document.getElementById(button.dataset.resetPrompt);
   const modified=!!box&&!!DEFAULTS[box.id]&&box.value.trim()!==DEFAULTS[box.id].trim();
   button.hidden=!modified;const note=button.previousElementSibling;if(note?.classList.contains('prompt-state'))note.textContent=modified?'Modified.':'Built-in prompt.'}
 }
 document.addEventListener('input',event=>{if(KEYS[event.target?.id])syncResets()});
 // what is saved: '' while the box holds the built-in prompt
 window.checkPromptValue=id=>{const box=document.getElementById(id);if(!box)return '';
  const value=box.value.trim();return !value||value===DEFAULTS[id].trim()?'':value};
 window.showCheckPrompts=settings=>{
  for(const [id,key] of Object.entries(KEYS)){const box=document.getElementById(id);
   if(!box||document.activeElement===box||settings?.[key]===undefined)continue;
   box.value=settings[key]||DEFAULTS[id]}
  syncResets();
 };
 document.addEventListener('click',event=>{const id=event.target?.dataset?.resetPrompt;if(!id)return;
  const box=document.getElementById(id);if(!box)return;box.value=DEFAULTS[id];
  box.dispatchEvent(new Event('change',{bubbles:true}));syncResets()});
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',loadDefaults);else loadDefaults();
})();
