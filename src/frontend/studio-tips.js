// Help text lives on the controls as hover tooltips: the explanation stays in the page for screen readers and
// search, but shows only when the pointer rests on the related label, field, button or demo frame.
(() => {
  const LONG = 60;
  const CONTROLS = ':scope > label, :scope > .field-head label, :scope > .field-head button, :scope > input, :scope > select, :scope > textarea, :scope > button, :scope > .row > input, :scope > .row > select, :scope > .row > button, :scope > .lettering-styles label, :scope > div > label, :scope > div > select, :scope > legend';
  const give = (elements, text) => { let given = false; for (const el of elements) { if (!el.title) { el.title = text; given = true; } } return given; };

  for (const help of document.querySelectorAll('#jobForm .help, #projectPanel .help')) {
    if (help.id || help.getAttribute('role') === 'status' || help.closest('.inspector-footer')) continue;
    const text = help.textContent.trim();
    if (text.length < LONG) continue;
    const previous = help.previousElementSibling;
    let targets;
    if (previous?.matches('canvas, .fx-sim')) targets = [previous];
    else if (help.parentElement.matches('.kinetic-controls')) targets = [help.parentElement.querySelector(':scope > label')];  // the group's own note sits on its title
    else if (help.parentElement.matches('.project-col, .ptab-col, .section-body, .typography-settings')) {  // a column note sits on the heading above it
      let heading = help.previousElementSibling; while (heading && !heading.matches('.eyebrow')) heading = heading.previousElementSibling;
      targets = heading ? [heading] : [];
    }
    else {
      const field = help.closest('.field, .effect-setting, .auto-accept-setting, .review-settings, .video-generation-setting, .scene-controls, .stage-controls, .profile-box') || help.parentElement;
      targets = [...field.querySelectorAll(CONTROLS)];
      if (!targets.length && previous) targets = [previous, ...previous.querySelectorAll('input, select, textarea, label')];
      if (!targets.length) targets = [field];
    }
    if (give(targets, text)) help.classList.add('tip-hidden');
  }
  // Live help (model descriptions, step hints) stays visible but short; the full text opens on hover.
  for (const help of document.querySelectorAll('#jobForm .help[id], #jobForm .help[role=status], #projectPanel .help[id], #projectPanel .help[role=status]')) { help.classList.add('clamp'); if (!help.title) help.title = help.textContent.trim(); }

  // Workspace panels: the description sits on the heading; the vision note on the Review all button.
  for (const small of document.querySelectorAll('.workspace .panel-head > div > small, .workspace .panel-head > small')) {
    const text = small.textContent.trim(); if (!text) continue;
    const h2 = small.closest('.panel-head').querySelector('h2');
    if (h2 && !h2.title) { h2.title = text; small.classList.add('tip-hidden'); }
  }
  const vision = document.querySelector('.vision-row > small');
  const verifyAll = document.getElementById('verifyAll');
  if (vision && verifyAll) { verifyAll.title = vision.textContent.trim(); vision.classList.add('tip-hidden'); }
})();
