// Projects: rename and delete with a confirmation dialog, used by the home list and the top bar.
(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('projectDialog'); if (!dialog) return;
  const title = $('projectDialogTitle'), text = $('projectDialogText'), input = $('projectDialogInput');
  const ok = $('projectDialogConfirm'), cancel = $('projectDialogCancel');
  let resolver = null;
  function open(options) {
    title.textContent = options.title; text.textContent = options.text || ''; text.hidden = !options.text;
    input.hidden = !options.input; input.value = options.value || '';
    ok.textContent = options.confirm || 'OK';
    ok.classList.toggle('danger-fill', !!options.danger); ok.classList.toggle('primary', !options.danger);
    dialog.showModal();
    if (options.input) { input.focus(); input.select(); } else ok.focus();
    return new Promise(resolve => { resolver = resolve; });
  }
  const close = value => { const done = resolver; resolver = null; dialog.close(); if (done) done(value); };
  ok.addEventListener('click', () => close(input.hidden ? true : input.value.trim()));
  cancel.addEventListener('click', () => close(null));
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(null); });
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); close(input.value.trim()); } });

  const optionFor = id => [...($('jobs')?.options || [])].find(o => o.value === id);
  const nameOf = id => { const o = optionFor(id); return o ? o.textContent.replace(/ [·\/] [^·]*$/, '') : id; };
  const current = () => (typeof jobId !== 'undefined' && jobId) ? jobId : '';

  async function rename(id, name) {
    const next = await open({ title: 'Rename project', input: true, value: name ?? nameOf(id), confirm: 'Save' });
    if (!next) return false;
    try {
      await api(`/api/jobs/${id}/rename`, { name: next });
      const option = optionFor(id); if (option) option.textContent = next + ' · ' + id;
      if (id === current() && $('projectName')) $('projectName').value = next;
      window.refreshHome?.(true); toast('Renamed to ' + next); return true;
    } catch (error) { toast(error.message); return false; }
  }
  async function remove(id, name) {
    const yes = await open({ title: 'Delete this project?', confirm: 'Delete', danger: true,
      text: `“${name ?? nameOf(id)}” leaves the studio. Its artwork, timings and exports move to the output folder's .trash, where they can be recovered by hand.` });
    if (!yes) return false;
    try {
      await api(`/api/jobs/${id}/delete`, {});
      const option = optionFor(id); const wasCurrent = current() === id;
      if (option) option.remove();
      if (wasCurrent) newSession();
      window.refreshHome?.(true); toast('Project deleted'); return true;
    } catch (error) { toast(error.message); return false; }
  }
  window.studioProjects = { rename, remove, ask: open };
  // The Project tab's name field renames an open project as soon as it is edited.
  $('projectName')?.addEventListener('change', async () => {
    const id = current(); const next = $('projectName').value.trim(); if (!id || !next || next === nameOf(id)) return;
    try { await api(`/api/jobs/${id}/rename`, { name: next }); const option = optionFor(id); if (option) option.textContent = next + ' · ' + id; window.refreshHome?.(true); toast('Renamed to ' + next); }
    catch (error) { toast(error.message); }
  });

  // A new project gets a name to start with; the field stays editable.
  window.defaultProjectName = () => {
    const field = $('projectName'); if (!field) return;
    const stamp = new Date().toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    field.value = 'Project · ' + stamp;
  };
})();
