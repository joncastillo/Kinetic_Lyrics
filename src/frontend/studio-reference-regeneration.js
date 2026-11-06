// Persistent reference recipes and their input pictures. Cancel leaves the recipe unchanged.
(() => {
  window.openReferenceRegeneration = async entity => {
    const project = jobId;
    let data;
    try {
      data = await api(`/api/jobs/${project}/reference-prompt`, {id:entity.id});
      if(typeof data.looks!=='string'||!Array.isArray(data.options))throw Error('Restart Studio and refresh this page to load the updated reference editor.');
    }
    catch (error) { toast(error.message || String(error)); return; }
    const dialog = document.createElement('dialog');
    dialog.className = 'reference-repaint-dialog reference-recipe';
    dialog.innerHTML = `<form><h3></h3><div class="reference-current-preview"><img alt="Current reference" hidden><p class="help" hidden>No current image. This recipe will generate a new reference.</p></div>
      <p class="help">Save edits into the storyline and use them for regeneration. Derived references and dependent illustrations are rebuilt too.</p>
      <label>Description used by the AI<textarea class="reference-description" rows="4" maxlength="4000" required></textarea></label>
      <label>Generation prompt<textarea class="reference-generation-prompt" rows="8" maxlength="12000" required></textarea></label>
      <details><summary>Last prompt sent to the image model</summary><textarea class="reference-last-prompt" rows="5" readonly></textarea></details>
      <section><div class="reference-input-heading"><strong>Reference pictures</strong><span class="reference-input-count help"></span></div>
        <p class="help">Select existing references or upload pictures. Choose whether each guides identity, art style, or detail.</p>
        <div class="reference-input-grid"></div>
        <label class="reference-upload">Add pictures <input type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
      </section>
      <p class="reference-impact help"></p><p class="reference-error" role="alert" hidden></p>
      <div class="row"><button type="button" class="reference-cancel">Cancel</button><button type="submit" class="primary">Save and regenerate</button></div>
      </form>`;
    const q = selector => dialog.querySelector(selector);
    const description = q('.reference-description'), prompt = q('.reference-generation-prompt');
    const submit = q('button[type=submit]'), cancel = q('.reference-cancel');
    let options = [...(data.options || [])], inputs = (data.inputs || []).map(x=>({...x})), busy = false;
    let previousDescription = data.looks || '';
    const key = input => input.kind+':'+input.id;
    q('h3').textContent = 'Regenerate '+(data.name || entity.name);
    dialog.setAttribute('aria-label', q('h3').textContent);
    const preview=q('.reference-current-preview img');
    if(data.current_image){preview.src=data.current_image;preview.alt=data.name||entity.name;preview.hidden=false}
    else q('.reference-current-preview p').hidden=false;
    description.value = previousDescription;
    prompt.value = data.prompt || '';
    q('.reference-last-prompt').value = data.last_prompt || 'This reference has no saved generation prompt yet.';
    q('.reference-impact').textContent = `${(data.dependents||[]).length} derived reference(s) and ${(data.images||[]).length} illustration(s) will be regenerated. `+
      ((data.dependents||[]).length ? 'Derived references: '+data.dependents.join(', ')+'. ' : '')+
      'Superseded output is removed from active use and archived for recovery.';
    const error = message => { q('.reference-error').textContent=message; q('.reference-error').hidden=!message; };
    const valid = () => {
      q('.reference-input-count').textContent = `${inputs.length} / ${data.max_references} selected`;
      submit.disabled = busy || !description.value.trim() || !prompt.value.trim() || inputs.length>data.max_references;
      cancel.disabled = busy;
    };
    function renderInputs() {
      q('.reference-input-grid').replaceChildren(...options.map(option => {
        const selected = inputs.find(input=>key(input)===key(option));
        const card = document.createElement('div');card.className='reference-input-card'+(selected?' selected':'');
        const label = document.createElement('label'), box=document.createElement('input');box.type='checkbox';box.checked=!!selected;
        const name=document.createElement('span');name.textContent=option.label;
        label.append(box,name);
        if(option.url){const image=document.createElement('img');image.src=option.url;image.alt=option.label;image.loading='lazy';label.append(image)}
        else{const pending=document.createElement('small');pending.textContent='Will be generated first';label.append(pending)}
        const role=document.createElement('select');role.setAttribute('aria-label','Use '+option.label+' for');
        for(const [value,text] of [['identity','Identity / appearance'],['style','Art style only'],['detail','Specific details']])role.add(new Option(text,value));
        role.value=selected?.role||option.role||'identity';role.disabled=!selected;
        box.onchange=()=>{inputs=inputs.filter(input=>key(input)!==key(option));if(box.checked)inputs.push({kind:option.kind,id:option.id,role:role.value});renderInputs();valid()};
        role.onchange=()=>{const item=inputs.find(input=>key(input)===key(option));if(item)item.role=role.value};
        card.append(label,role);return card;
      }));
      valid();
    }
    description.oninput=()=>{
      const old=previousDescription.trim().replace(/[.\s]+$/g,''), next=description.value.trim().replace(/[.\s]+$/g,'');
      if(old&&prompt.value.includes(old))prompt.value=prompt.value.replace(old,next);
      else if(next)prompt.value+='\n\nUpdated subject description: '+next+'.';
      previousDescription=description.value;valid();
    };
    prompt.oninput=valid;
    q('input[type=file]').onchange=async event=>{
      const files=[...event.target.files];event.target.value='';if(!files.length)return;
      if(inputs.length+files.length>data.max_references){error(`Select at most ${data.max_references} pictures in total.`);return}
      busy=true;valid();error('');
      try {
        const form=new FormData();files.forEach(file=>form.append('reference',file));
        const answer=await api(`/api/jobs/${project}/reference-input-upload`,form);
        for(const item of answer.added||[]){if(!options.some(x=>key(x)===key(item)))options.push(item);if(!inputs.some(x=>key(x)===key(item)))inputs.push({kind:item.kind,id:item.id,role:item.role})}
        renderInputs();
      } catch(e){error(e.message||String(e))}finally{busy=false;valid()}
    };
    cancel.onclick=()=>dialog.close();
    dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault()});
    dialog.addEventListener('close',()=>dialog.remove());
    q('form').onsubmit=async event=>{
      event.preventDefault();if(submit.disabled)return;
      busy=true;valid();error('');
      try {
        const answer=await api(`/api/jobs/${project}/reference-repaint`,{id:entity.id,revision:data.revision,looks:description.value,prompt:prompt.value,inputs},120000);
        toast(answer.message||'Reference recipe saved.');artworkRefsSignature='';dialog.close();window.poll?.();
      } catch(e){error(e.message||String(e));busy=false;valid()}
    };
    document.body.append(dialog);renderInputs();dialog.showModal();
  };
})();
