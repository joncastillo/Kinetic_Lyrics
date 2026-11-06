// Home screen: a reel of finished videos and the list of sessions, built from the job list the server keeps.
(() => {
  const $ = id => document.getElementById(id);
  const home = $('homePanel'); if (!home) return;
  const reel = home.querySelector('.reel'), dots = home.querySelector('.reel-dots'), list = home.querySelector('.session-list');
  const fmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const when = job => { const t = job.finished || job.started; return t ? fmt.format(new Date(t * 1000)) : ''; };
  const hidden = () => { try { return new Set(JSON.parse(localStorage.getItem('lyricStudioRemovedSongs') || '[]')); } catch { return new Set(); } };

  function openJob(id) {
    const jobs = $('jobs'); if (!jobs) return;
    if (![...jobs.options].some(o => o.value === id)) jobs.add(new Option(id, id));
    jobs.value = id; jobs.dispatchEvent(new Event('change'));
  }
  window.openStudioJob = openJob;

  const STATE = { complete: ['✓', 'Complete'], running: ['⟳', 'Running'], queued: ['⟳', 'Queued'], review: ['⟳', 'Waiting for review'], failed: ['✕', 'Failed'], cancelled: ['⊘', 'Stopped'] };
  function badges(job) {
    const wrap = document.createElement('span'); wrap.className = 'thumb-badges';
    const media = document.createElement('i'); media.className = 'media ' + (job.video ? 'video' : 'image');
    media.textContent = job.video ? '▶' : '▣'; media.title = job.video ? 'Video rendered' : job.has_images ? 'Images only' : 'No artwork yet';
    if (!job.video && !job.has_images) media.classList.add('none');
    const [glyph, label] = STATE[job.status] || ['·', 'New'];
    const state = document.createElement('i'); state.className = 'state ' + (job.status || 'new'); state.textContent = glyph; state.title = label;
    wrap.append(media, state);
    return wrap;
  }
  function reelCard(job) {
    const card = document.createElement('button');
    card.type = 'button'; card.className = 'reel-card'; card.setAttribute('aria-label', 'Open ' + job.name);
    card.append(badges(job));
    if (job.poster) { const img = document.createElement('img'); img.src = job.poster; img.alt = ''; img.loading = 'lazy'; card.append(img); }
    if (job.video) {
      const video = document.createElement('video'); video.src = job.video; video.muted = true; video.loop = true; video.playsInline = true; video.preload = 'none';
      card.append(video);
      card.addEventListener('mouseenter', () => { video.currentTime = Math.min(8, video.duration || 8); video.play().catch(() => {}); });
      card.addEventListener('mouseleave', () => { video.pause(); });
    }
    const meta = document.createElement('div'); meta.className = 'reel-meta';
    meta.innerHTML = `<div><b></b><span></span></div><span class="reel-play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span>`;
    meta.querySelector('b').textContent = job.name; meta.querySelector('div > span').textContent = when(job);
    card.append(meta);
    card.addEventListener('click', () => openJob(job.id));
    return card;
  }

  function sessionRow(job) {
    const row = document.createElement('button'); row.type = 'button'; row.className = 'session-row';
    const thumb = document.createElement('span'); thumb.className = 'thumb-wrap';
    thumb.append(job.poster ? Object.assign(document.createElement('img'), { src: job.poster, alt: '', className: 'thumb', loading: 'lazy' })
      : Object.assign(document.createElement('span'), { className: 'thumb blank', textContent: '♪' }), badges(job));
    const text = document.createElement('span');
    text.innerHTML = '<span class="name"></span><span class="when"></span>';
    text.querySelector('.name').textContent = job.name; text.querySelector('.when').textContent = when(job);
    const badge = document.createElement('span'); badge.className = 'badge ' + (job.status || 'new'); badge.textContent = (STATE[job.status] || ['', 'New'])[1];
    const actions = document.createElement('span'); actions.className = 'row-actions';
    const rename = document.createElement('button'); rename.type = 'button'; rename.className = 'icon-button'; rename.title = 'Rename'; rename.setAttribute('aria-label', 'Rename ' + job.name);
    rename.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
    rename.addEventListener('click', event => { event.stopPropagation(); window.studioProjects?.rename(job.id, job.name); });
    const del = document.createElement('button'); del.type = 'button'; del.className = 'icon-button danger'; del.title = 'Delete'; del.setAttribute('aria-label', 'Delete ' + job.name);
    del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/></svg>';
    del.addEventListener('click', event => { event.stopPropagation(); window.studioProjects?.remove(job.id, job.name); });
    actions.append(rename, del);
    row.append(thumb, text, badge, actions);
    row.addEventListener('click', () => openJob(job.id));
    return row;
  }

  // a job this page did not start or open, such as one begun through the backend: stated here without selecting it, so
  // the pipeline shows nothing of it
  const BACKGROUND = { running: 'Running', queued: 'Queued', review: 'Waiting for review' };
  function showBackgroundJob(jobs) {
    const box = document.getElementById('backgroundJob'), text = document.getElementById('backgroundJobText');
    if (!box || !text) return;
    const open = typeof jobId !== 'undefined' ? jobId : '';
    const job = jobs.find(j => j.id !== open && ['running', 'queued'].includes(j.status)) || jobs.find(j => j.id !== open && j.status === 'review');
    box.hidden = !job;
    text.textContent = job ? `${job.name}: ${BACKGROUND[job.status]}` : '';
  }

  let rendered = '';
  async function render() {
    let jobs = [];
    try { const cfg = await (await fetch('/api/config', { cache: 'no-store' })).json(); jobs = cfg.jobs || []; } catch { return; }
    const removed = hidden();
    jobs = jobs.filter(j => !removed.has(j.id));
    showBackgroundJob(jobs);
    const key = JSON.stringify(jobs.map(j => [j.id, j.name, j.status, j.video, j.poster, j.has_images]));
    if (key === rendered) return; rendered = key;
    const finished = jobs.filter(j => j.video);
    window.homePoster = finished.find(j => j.poster)?.poster || '';
    reel.replaceChildren(...finished.map(reelCard));
    reel.closest('.reel-wrap').style.display = finished.length ? '' : 'none';
    list.replaceChildren(...jobs.map(sessionRow));
    if (!jobs.length) { const p = document.createElement('p'); p.className = 'help'; p.textContent = 'No sessions yet.'; list.append(p); }
    markDot();
  }
  function markDot() {
    if (!dots?.children.length) return;
    const cards = [...reel.querySelectorAll('.reel-card')]; if (!cards.length) return;
    const left = reel.getBoundingClientRect().left;
    let best = 0, dist = Infinity;
    cards.forEach((c, i) => { const d = Math.abs(c.getBoundingClientRect().left - left - 6); if (d < dist) { dist = d; best = i; } });
    [...dots.children].forEach((d, i) => d.setAttribute('aria-current', String(i === best)));
  }
  reel.addEventListener('scroll', () => requestAnimationFrame(markDot), { passive: true });
  home.querySelector('#homeNew')?.addEventListener('click', () => { $('newSessionButton')?.click(); window.defaultProjectName?.(); setTimeout(() => $('projectName')?.select(), 100); });
  home.querySelectorAll('.home-steps li').forEach(li => li.addEventListener('click', () => { $('newSessionButton')?.click(); window.defaultProjectName?.(); if (li.dataset.step !== 'project') window.openStudioSettings?.(li.dataset.step); }));
  window.refreshHome = force => { if (force) rendered = ''; return render(); };
  render(); setInterval(render, 8000);
})();
