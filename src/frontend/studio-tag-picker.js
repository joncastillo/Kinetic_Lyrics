// References in the edit fields. Typing @ lists the ones that match; clicking a tag lists them all, with a box to filter
// them. Every tag is coloured by the reference it names, and one naming nothing is red: the prompt drops it silently.
(() => {
  const FIELDS = 'textarea:not(#lyrics):not(#imageCheckPrompt):not(#referenceCheckPrompt):not(#referencePrompt):not(.reference-repaint-dialog textarea)';
  const TAG = /(^|[\s("'])(@(?:"[^"]+"|[\w-]+(?:\.\w+)?))/g;
  const HUES = [210, 28, 140, 330, 265, 55, 185, 95];
  const key = text => String(text).toLowerCase().replace(/[^a-z0-9]+/g, '');
  const colour = index => `hsl(${HUES[index % HUES.length]} 85% 65%)`;

  // The tags of the open dialog are the pictures that image is given; elsewhere, what the project has.
  const offered = box => {
    const maker = box.closest('.image-maker');   // the pictures in use there, and nothing of the song's
    if (maker) return window.imageEditorTags?.() || [...new Set([...maker.querySelectorAll('.ref-tag')].map(tag => tag.dataset.tag))];
    // a segment of the storyline: only that illustration's references, and the project's photos
    const segment = box.closest('.story-segment');
    if (segment) {
      const photos = (state?.render_settings?.references || []).map((_, index) => '@photo' + (index + 1));
      return [...new Set([...photos, ...[...segment.querySelectorAll('.story-ref .ref-tag')].map(tag => tag.dataset.tag)])];
    }
    const dialog = box.closest('dialog');
    const shown = [...(dialog || document).querySelectorAll('.ref-tag')].map(tag => tag.dataset.tag);
    if (dialog?.id === 'regenerateModal') return [...new Set(shown.filter(Boolean))];
    const photos = (state?.render_settings?.references || []).map((_, index) => '@photo' + (index + 1));
    const entities = entityReferences(state).filter(e => e.name && !e.cast && e.url).map(e => referenceTag(e.name));
    return [...new Set([...shown, ...photos, ...entities].filter(Boolean))];
  };

  const tagsIn = text => [...text.matchAll(TAG)].map(found => {
    const start = found.index + found[1].length;
    return { text: found[2], start, end: start + found[2].length };
  });
  const colourOf = (tag, tags) => {
    const wanted = key(tag), bare = key(tag.replace(/\.\w+$/, ''));
    const index = tags.findIndex(t => key(t) === wanted || key(t.replace(/\.\w+$/, '')) === bare);
    return index < 0 ? null : colour(index);
  };

  // @image1 counts the illustration's own pictures, as direction.entities.reference_tags does.
  const ownPicture = (tag, box) => {
    const found = /^@image\s*(\d+)$/i.exec(tag);
    const own = box.closest('.image-maker')?.querySelectorAll('.ref-tag').length
      ?? box.closest('.story-segment')?.querySelectorAll('.story-ref:not(.story-entity) .ref-tag').length
      ?? box.closest('dialog')?.querySelectorAll('#regenerateOwnRefs .ref-tag').length ?? 0;
    return !!found && +found[1] >= 1 && +found[1] <= own;
  };
  const known = (tag, tags, box) => !!colourOf(tag, tags) || ownPicture(tag, box);

  // Highlights: a copy of the text behind a see-through field, as the lyrics box does. It exists only while there are
  // tags, so a field without any is left exactly as it was.
  const marks = new WeakMap(), watched = new WeakSet();
  const COPIED = ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent',
    'tabSize', 'paddingTop', 'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth',
    'borderLeftWidth', 'borderRadius', 'backgroundColor', 'backgroundImage'];
  const escape = text => text.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

  const fit = box => {
    const layer = marks.get(box);
    if (!layer) return;
    const style = getComputedStyle(box);
    const bar = box.offsetWidth - box.clientWidth - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
    layer.style.left = box.offsetLeft + 'px'; layer.style.top = box.offsetTop + 'px';
    layer.style.width = box.offsetWidth + 'px'; layer.style.height = box.offsetHeight + 'px';
    layer.style.paddingRight = parseFloat(style.paddingRight) + bar + 'px';
    layer.scrollTop = box.scrollTop;
  };

  const paint = box => {
    const found = tagsIn(box.value);
    let layer = marks.get(box);
    if (!found.length) {
      if (layer) { layer.remove(); marks.delete(box); box.style.removeProperty('background'); box.style.removeProperty('position'); box.style.removeProperty('z-index'); }
      return;
    }
    if (!layer) {
      layer = document.createElement('div'); layer.className = 'tag-marks'; layer.setAttribute('aria-hidden', 'true');
      const style = getComputedStyle(box);
      COPIED.forEach(name => { layer.style[name] = style[name]; });
      box.before(layer); marks.set(box, layer);
      box.style.background = 'transparent'; box.style.position = 'relative'; box.style.zIndex = '1';
    }
    const tags = offered(box);
    let html = '', at = 0;
    for (const tag of found) {
      const shade = colourOf(tag.text, tags) || (ownPicture(tag.text, box) ? colour(0) : null);
      html += escape(box.value.slice(at, tag.start))
        + `<mark${shade ? ` style="--tag:${shade}"` : ' class="unknown"'}>${escape(tag.text)}</mark>`;
      at = tag.end;
    }
    html += escape(box.value.slice(at)) + '\n';
    if (layer.innerHTML !== html) layer.innerHTML = html;
    fit(box);
  };

  const watch = box => {
    if (watched.has(box)) return;
    watched.add(box);
    box.addEventListener('scroll', () => { const layer = marks.get(box); if (layer) layer.scrollTop = box.scrollTop; });
    new ResizeObserver(() => fit(box)).observe(box);
  };

  // Fields are filled by code too, so everything is painted again whenever the page changes.
  // A tag naming nothing is dropped from the prompt without a word, so a new picture would quietly lack that reference:
  // Replace and Verify wait until every tag in the fields that make up the prompt is one the model is given.
  const PROMPT_FIELDS = ['regenerateStyle', 'regenerateEnvironment', 'regenerateCharacters', 'regeneratePrompt'];
  const invalidTags = () => {
    const bad = PROMPT_FIELDS.map(id => document.getElementById(id)).filter(Boolean).flatMap(box => {
      const tags = offered(box);
      return tagsIn(box.value).map(tag => tag.text).filter(tag => !known(tag, tags, box));
    });
    return [...new Set(bad)];
  };
  const showInvalid = () => {
    const row = document.getElementById('submitRegenerate')?.parentElement;
    if (!row) return [];
    let note = document.getElementById('regenerateTagWarning');
    if (!note) { note = document.createElement('p'); note.id = 'regenerateTagWarning'; note.className = 'tag-warning'; note.setAttribute('role', 'alert'); row.before(note); }
    const bad = invalidTags();
    note.hidden = !bad.length;
    note.textContent = bad.length ? `Fix before generating, no picture has ${bad.length > 1 ? 'these tags' : 'this tag'}: ${bad.join(', ')}` : '';
    for (const id of ['submitRegenerate', 'verifyRegenerate']) document.getElementById(id)?.classList.toggle('tag-blocked', !!bad.length);
    return bad;
  };
  document.addEventListener('click', event => {
    if (!event.target.closest?.('#submitRegenerate,#verifyRegenerate') || !showInvalid().length) return;
    event.preventDefault(); event.stopImmediatePropagation();   // ahead of the button's own handler
  }, true);

  window.invalidTagsIn = boxes => [...new Set(boxes.flatMap(box => {
    const tags = offered(box);
    return tagsIn(box.value).map(tag => tag.text).filter(tag => !known(tag, tags, box));
  }))];

  // The storyline's image prompts, for the button that remakes the whole song: [{number, tags}] of those with bad tags.
  window.storyTagProblems = dialog => [...dialog.querySelectorAll('.story-segment')].flatMap(segment => {
    const box = segment.querySelector('textarea[data-field="prompt"]');
    if (!box) return [];
    const tags = offered(box);
    const bad = [...new Set(tagsIn(box.value).map(tag => tag.text).filter(tag => !known(tag, tags, box)))];
    return bad.length ? [{ number: +segment.dataset.index + 1, tags: bad }] : [];
  });

  const paintAll = () => {
    document.querySelectorAll(FIELDS).forEach(box => { watch(box); paint(box); });
    if (document.getElementById('regenerateModal')?.open) showInvalid();
    document.querySelectorAll('dialog[open]').forEach(dialog => {
      const box = dialog.querySelector(FIELDS);
      if (box) { const tags = offered(box); dialog.querySelectorAll('.ref-tag').forEach(tag => tag.style.setProperty('--tag', colourOf(tag.dataset.tag, tags))); }
    });
  };
  let waiting = 0;
  new MutationObserver(changes => {
    if (changes.every(change => change.target.closest?.('.tag-marks,.tag-picker'))) return;
    clearTimeout(waiting); waiting = setTimeout(paintAll, 120);
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });

  // The list: filtered by what follows the @, or by its own box after a click on a tag.
  const list = document.createElement('div');
  list.className = 'tag-picker'; list.popover = 'manual';
  const filter = document.createElement('input');
  filter.type = 'search'; filter.placeholder = 'Filter references…'; filter.setAttribute('aria-label', 'Filter references');
  const rows = document.createElement('div');
  rows.setAttribute('role', 'listbox');
  list.append(filter, rows);
  let field = null, from = 0, to = 0, matches = [], current = 0, tags = [], picking = false;
  const isOpen = () => list.matches(':popover-open');
  const close = () => { field = null; if (isOpen()) list.hidePopover(); };

  const choose = tag => {
    const box = field, typed = filter.hidden;
    box.focus();
    box.setRangeText(tag + (typed ? ' ' : ''), from, to, 'end');
    close();
    picking = true;   // the tag just put in must not open the list again
    box.dispatchEvent(new Event('input', { bubbles: true }));
    picking = false;
  };

  const showRows = () => {
    rows.replaceChildren(...matches.map((tag, index) => {
      const row = document.createElement('button');
      row.type = 'button'; row.tabIndex = -1; row.textContent = tag;
      row.style.setProperty('--tag', colourOf(tag, tags));
      row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(index === current));
      row.onmousedown = event => { event.preventDefault(); choose(tag); };   // the field keeps its focus
      return row;
    }));
    if (!matches.length) {
      const none = document.createElement('p');
      none.textContent = tags.length ? 'No reference matches this.' : 'This image has no references yet.';
      rows.append(none);
    }
    rows.children[current]?.scrollIntoView({ block: 'nearest' });
  };

  const narrow = text => {
    const wanted = key(text);
    matches = tags.filter(tag => key(tag).includes(wanted)).sort((a, b) => key(b).startsWith('' + wanted) - key(a).startsWith('' + wanted));
    current = 0; showRows();
  };

  const place = box => {
    const home = box.closest('dialog') || document.body;   // anything outside a modal dialog cannot be clicked
    if (list.parentNode !== home) { if (isOpen()) list.hidePopover(); home.append(list); }
    if (!isOpen()) list.showPopover();
    const rect = box.getBoundingClientRect(), height = list.offsetHeight;
    list.style.left = rect.left + 'px'; list.style.width = rect.width + 'px';
    list.style.top = (rect.bottom + 4 + height <= innerHeight ? rect.bottom + 4 : Math.max(4, rect.top - height - 4)) + 'px';
  };

  document.addEventListener('input', event => {
    const box = event.target;
    if (box === filter) return narrow(filter.value);
    if (!box.matches?.(FIELDS)) return;
    paint(box);
    if (PROMPT_FIELDS.includes(box.id)) showInvalid();
    if (picking) return;
    const found = /(?:^|[\s("'])@([\w.-]*)$/.exec(box.value.slice(0, box.selectionStart));
    if (!found) return close();
    field = box; to = box.selectionStart; from = to - found[1].length - 1;
    tags = offered(box); filter.hidden = true;
    narrow(found[1]); place(box);
  });

  document.addEventListener('click', event => {
    const box = event.target;
    if (list.contains(box)) return;
    if (!box.matches?.(FIELDS) || box.selectionStart !== box.selectionEnd) return close();
    const tag = tagsIn(box.value).find(t => t.start <= box.selectionStart && box.selectionStart <= t.end);
    if (!tag) return close();
    field = box; from = tag.start; to = tag.end;
    tags = offered(box); filter.hidden = false; filter.value = '';
    narrow(''); place(box); filter.focus();
  });

  // Capturing, so Escape closes the list and not the dialog around it.
  document.addEventListener('keydown', event => {
    if (!field || !isOpen()) return;
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step && matches.length) { current = (current + step + matches.length) % matches.length; showRows(); }
    else if ((event.key === 'Enter' || event.key === 'Tab') && matches.length) choose(matches[current]);
    else if (event.key === 'Escape') { const box = field; close(); box.focus(); }
    else if (event.key === 'Enter' && !filter.hidden) { /* nothing to pick: the box stays open */ }
    else return;
    event.preventDefault(); event.stopPropagation();
  }, true);

  document.addEventListener('focusout', event => {
    if (field && !list.contains(event.relatedTarget) && event.relatedTarget !== field) close();
  });
  addEventListener('load', paintAll);

  // A tag written into a page's HTML has no handler of its own (see tagCaption): it copies all the same.
  document.addEventListener('click', event => {
    const tag = event.target.closest?.('.story-entity-photo .ref-tag,.story-ref .ref-tag');
    if (!tag) return;
    copyText(tag.dataset.tag, tag.parentNode).then(() => {
      tag.textContent = 'Copied'; setTimeout(() => { tag.textContent = tag.dataset.tag; }, 1200);
    }).catch(() => {});
  });
})();
