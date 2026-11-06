/* Live previews of the beat effects and the will-o'-wisp, drawn from the current kinetic settings. They mimic the
   renderer (render/drum_typography.py shake_background, render/chorus_fx.py lights and confetti, the wisp in
   render/realtime.py) closely enough to judge the settings without rendering a video. */
(() => {
  const TAU = Math.PI * 2;
  const settings = () => (typeof kineticSettings === 'function' ? kineticSettings() : {});
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function fit(canvas) {
    const ratio = Math.min(2, devicePixelRatio || 1), w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
      canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
    }
    return [canvas.width, canvas.height];
  }

  // A small painted scene: dusk sky, sun, sea and hills, standing in for the illustration.
  function scenery(g, w, h) {
    const sky = g.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, '#2b3a78'); sky.addColorStop(.55, '#f08a5d'); sky.addColorStop(.62, '#f7c56b');
    sky.addColorStop(.63, '#3c7fa8'); sky.addColorStop(1, '#173a5c');
    g.fillStyle = sky; g.fillRect(0, 0, w, h);
    g.fillStyle = '#ffe3a1'; g.beginPath(); g.arc(w * .68, h * .55, h * .09, 0, TAU); g.fill();
    g.fillStyle = '#21304f';
    g.beginPath(); g.moveTo(0, h * .63);
    for (let x = 0; x <= w; x += w / 24) g.lineTo(x, h * (.6 - .06 * Math.sin(x / w * 7) - .03 * Math.sin(x / w * 17)));
    g.lineTo(w, h * .63); g.closePath(); g.fill();
    g.strokeStyle = 'rgba(255,255,255,.18)'; g.lineWidth = Math.max(1, h * .004);
    for (let k = 0; k < 6; k++) { const y = h * (.7 + k * .05); g.beginPath(); g.moveTo(w * .1 * k, y); g.lineTo(w * (.4 + .1 * k), y); g.stroke(); }
  }

  function heart(g, x, y, size, angle) {
    g.save(); g.translate(x, y); g.rotate(angle); g.beginPath();
    for (let k = 0; k <= 20; k++) {
      const t = TAU * k / 20, hx = 16 * Math.sin(t) ** 3 / 17;
      const hy = -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) / 17;
      k ? g.lineTo(hx * size, hy * size) : g.moveTo(hx * size, hy * size);
    }
    g.fill(); g.restore();
  }

  // ---- Beat effects ------------------------------------------------------------------------------------------
  const BEAT = .5, LOOP = 8, CHORUS = [4, 8];  // 120 bpm kicks; a verse then a chorus
  const COLORS = ['#ffd254', '#45d0ff', '#ff579f', '#ad87ff', '#f4f6ff'];
  function beatFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), s = settings();
    const t = (now / 1000) % LOOP, chorus = t >= CHORUS[0] && t < CHORUS[1];
    const scope = s.beat_scope || 'chorus', inScope = scope === 'song' || chorus;
    const kick = Math.floor(t / BEAT), age = t - kick * BEAT, strength = kick % 4 === 0 ? 1 : .75;
    const shake = +s.background_shake || 0, intensity = s.beat_intensity ?? .75, effect = s.beat_effect || 'lights';
    // Background shake: punched in and thrown sideways, as shake_background does.
    g.save();
    if (inScope && shake > 0) {
      const weight = .55 + .45 * strength, side = Math.min(w, h);
      const reach = side * .045 * Math.min(1, shake) * weight * Math.exp(-age * 7);
      const dx = reach * Math.cos(age * 62 + kick * 1.7), dy = reach * .7 * Math.sin(age * 79 + kick * 2.3);
      const punch = .045 * Math.min(1, shake) * weight * Math.exp(-age * 9), scale = 1 + 2 * (Math.abs(dx) + Math.abs(dy)) / side + punch;
      g.translate(w / 2 + dx, h / 2 + dy); g.scale(scale, scale); g.translate(-w / 2, -h / 2);
    }
    scenery(g, w, h); g.restore();
    const blur = inScope ? (+s.beat_blur || 0) * Math.exp(-age / .12 * 1.0) * Math.min(w, h) * .012 * (.35 + .65 * strength) : 0;
    if (inScope && effect === 'dim' && intensity > 0) {
      g.fillStyle = `rgba(0,0,0,${Math.min(1, intensity) * .6 * (.55 + .45 * strength) * Math.exp(-age * 6)})`; g.fillRect(0, 0, w, h);
    }
    if (inScope && effect === 'lights' && intensity > 0) {
      const energy = intensity * (.35 + .65 * Math.exp(-age / .23 * 1.5));
      const layouts = [['tl', 'tr'], ['bl', 'br'], ['tl', 'br'], ['bl', 'tr']], layout = layouts[Math.floor(kick / 4) % 4];
      const sway = Math.sin(t * 1.7) * w * .11;
      g.save(); g.globalCompositeOperation = 'screen'; g.filter = `blur(${Math.max(2, w * .012)}px)`;
      layout.forEach((corner, n) => {
        g.save();
        g.translate(corner[1] === 'r' ? w : 0, corner[0] === 'b' ? h : 0); g.scale(corner[1] === 'r' ? -1 : 1, corner[0] === 'b' ? -1 : 1);
        const lean = (corner === 'tl' || corner === 'br') ? sway : -sway;
        g.fillStyle = n ? `rgba(255,83,158,${.36 * energy})` : `rgba(73,202,255,${.36 * energy})`;
        g.beginPath(); g.moveTo(0, 0); g.lineTo(w * .29, 0); g.lineTo(w * .72 + lean, h); g.lineTo(w * .6 + lean, h); g.closePath(); g.fill();
        g.fillStyle = n ? `rgba(255,201,89,${.57 * energy})` : `rgba(76,205,255,${.57 * energy})`;
        g.beginPath(); g.ellipse(w * .09, h * .02, w * .22, w * .2, 0, 0, TAU); g.fill();
        g.restore();
      });
      g.restore();
    }
    // Lyric-shaped confetti: a burst as the chorus opens and on every fourth (strong) kick in scope.
    if (s.beat_confetti ?? true) {
      // Pieces per burst follow the slider as the renderer does: thin below the default, four times at 100%,
      // and bursts land on every second kick from 85% and every kick from 95%.
      const level = s.confetti_intensity ?? .85, base = .85;
      const pieces = level <= base ? Math.max(.15, (level / base) ** 2) : 1 + 3 * ((level - base) / (1 - base)) ** 2;
      const every = level >= .95 ? 1 : level >= base ? 2 : 4;
      const bursts = [];
      if (t >= CHORUS[0] && t < CHORUS[0] + 2.2) bursts.push([CHORUS[0], Math.round(18 * pieces), 1]);
      for (let k = Math.max(0, kick - 5); k <= kick; k++) {
        const when = k * BEAT, inside = scope === 'song' || (when >= CHORUS[0] && when < CHORUS[1]);
        if (k % every === 0 && inside && t - when <= 2.15) bursts.push([when, Math.round(4 * pieces), 1]);
      }
      for (const [when, count, weight] of bursts) {
        const a = t - when, fade = Math.max(0, Math.min(1, (2.15 - a) / .55));
        for (let n = 0; n < count; n++) {
          const r = Math.sin((when * 97 + n) * 12.9898) * 43758.5453, rnd = r - Math.floor(r);
          const r2 = Math.sin((when * 31 + n) * 78.233) * 12345.678, rnd2 = r2 - Math.floor(r2);
          const side = n % 2 ? -1 : 1, cannon = n % 3 === 0;  // every third piece from a side cannon, the rest from anywhere along the bottom
          const x0 = cannon ? w * (side > 0 ? .04 : .96) : w * (.02 + .96 * rnd2), vx = cannon ? side * w * (.12 + .38 * rnd) : w * (rnd2 - .5) * .9;
          const x = x0 + vx * a + Math.sin(a * 5 + n) * w * .012;
          const y = h * (.78 + .08 * rnd2) - h * (.3 + .95 * rnd) * a + h * .43 * a * a;
          g.fillStyle = COLORS[n % COLORS.length]; g.globalAlpha = Math.min(1, level / base) * fade * weight;
          heart(g, x, y, Math.min(w, h) * (.018 + .02 * rnd), a * (3 + 5 * rnd) + n * .73);
        }
      }
      g.globalAlpha = 1;
    }
    // The lyric stays steady: it rides the camera layer, not the background.
    g.fillStyle = '#fff'; g.font = `800 ${Math.round(h * .1)}px system-ui, sans-serif`; g.textAlign = 'center';
    g.shadowColor = 'rgba(0,0,0,.5)'; g.shadowBlur = h * .02; g.fillText('FALLING IN LOVE', w / 2, h * .38); g.shadowBlur = 0;
    if (blur >= .4) {  // the whole screen blurs on the kick, as the renderer does
      const copy = document.createElement('canvas'); copy.width = w; copy.height = h; copy.getContext('2d').drawImage(canvas, 0, 0);
      g.save(); g.filter = `blur(${blur}px)`; g.drawImage(copy, 0, 0); g.restore();
    }
    // Section strip and kick marks.
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(0, h * .9, w, h * .1);
    g.fillStyle = 'rgba(255,255,255,.18)'; g.fillRect(w * CHORUS[0] / LOOP, h * .9, w * (CHORUS[1] - CHORUS[0]) / LOOP, h * .1);
    g.fillStyle = '#d5f59b'; g.fillRect(w * t / LOOP - 1, h * .9, 2, h * .1);
    g.font = `600 ${Math.round(h * .05)}px system-ui, sans-serif`; g.fillStyle = '#fff'; g.textAlign = 'left';
    g.fillText('Verse', w * .02, h * .965); g.fillText('Chorus', w * .52, h * .965);
    g.textAlign = 'right'; g.fillStyle = inScope ? '#d5f59b' : 'rgba(255,255,255,.55)';
    g.fillText(inScope ? 'beat effects on' : 'beat effects off here', w * .98, h * .965);
  }

  // ---- Will-o'-wisp ------------------------------------------------------------------------------------------
  const WORDS = [['Wise', .2, .42], ['men', .38, .42], ['SAY', .62, .4, true], ['only', .3, .62], ['FOOLS', .58, .62, true], ['rush', .78, .62]];
  const WISP_LOOP = 7;
  function shapePoints(kind, x, y, r) {
    const sides = kind === 'triangle' ? 3 : kind === 'square' ? 4 : 6;
    return Array.from({ length: sides + 1 }, (_, k) => {
      const a = -Math.PI / 2 + TAU * k / sides; return [x + Math.cos(a) * r, y + Math.sin(a) * r];
    });
  }
  function wispFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), s = settings();
    const t = (now / 1000) % WISP_LOOP;
    g.fillStyle = '#0f1830'; g.fillRect(0, 0, w, h);
    const glow = g.createRadialGradient(w * .5, h * .5, 0, w * .5, h * .5, w * .6);
    glow.addColorStop(0, 'rgba(80,110,180,.25)'); glow.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = glow; g.fillRect(0, 0, w, h);
    const heroes = WORDS.filter(word => word[3]);
    const shaped = Math.round((+s.word_shapes || 0) * heroes.length);   // hero words that get a traced shape
    const framed = (+s.frames || 0) > 0;
    const traces = s.traces ?? true;
    // Path: frame round line 1 (if framed), word to word, round each shaped hero word.
    const path = [];
    const add = (x, y) => path.push([x * w, y * h]);
    if (framed) for (let k = 0; k <= 24; k++) { const a = Math.PI + TAU * k / 24; add(.42 + Math.cos(a) * .3, .4 + Math.sin(a) * .1); }
    let heroCount = 0;
    for (const [text, x, y, hero] of WORDS) {
      add(x, y + .06);
      if (hero && heroCount++ < shaped) shapePoints(heroCount % 2 ? 'triangle' : 'hexagon', x, y - .02, .11).forEach(([px, py]) => add(px, py));
    }
    // The wisp never turns on a corner: the stops are threaded on a centripetal Catmull-Rom spline (as the
    // renderer's thread_curve bends between hero words) and the spline is what the head and tail follow.
    const stops = path, curve = [];
    const seg = (p0, p1, p2, p3) => {
      const tj = (a, b, prev) => prev + Math.pow(Math.hypot(b[0] - a[0], b[1] - a[1]), .5) || prev + 1e-6;
      const t0 = 0, t1 = tj(p0, p1, t0), t2 = tj(p1, p2, t1), t3 = tj(p2, p3, t2);
      for (let k = 0; k < 8; k++) {
        const u = t1 + (t2 - t1) * k / 8, lerp = (a, b, ta, tb) => [a[0] + (b[0] - a[0]) * (u - ta) / (tb - ta || 1e-6), a[1] + (b[1] - a[1]) * (u - ta) / (tb - ta || 1e-6)];
        const a1 = lerp(p0, p1, t0, t1), a2 = lerp(p1, p2, t1, t2), a3 = lerp(p2, p3, t2, t3);
        const b1 = lerp(a1, a2, t0, t2), b2 = lerp(a2, a3, t1, t3);
        curve.push(lerp(b1, b2, t1, t2));
      }
    };
    for (let k = 0; k < stops.length - 1; k++) seg(stops[Math.max(0, k - 1)], stops[k], stops[k + 1], stops[Math.min(stops.length - 1, k + 2)]);
    if (stops.length) curve.push(stops[stops.length - 1]);
    const lengths = [0]; for (let k = 1; k < curve.length; k++) lengths.push(lengths[k - 1] + Math.hypot(curve[k][0] - curve[k - 1][0], curve[k][1] - curve[k - 1][1]));
    const total = lengths[lengths.length - 1], progress = Math.min(1, t / (WISP_LOOP - 1.2)) * total;
    const at = d => { let k = lengths.findIndex(v => v >= d); if (k <= 0) return curve[0]; const f = (d - lengths[k - 1]) / (lengths[k] - lengths[k - 1] || 1);
      return [curve[k - 1][0] + (curve[k][0] - curve[k - 1][0]) * f, curve[k - 1][1] + (curve[k][1] - curve[k - 1][1]) * f]; };
    const nearest = (x, y) => { let best = 0, bestD = Infinity; curve.forEach((p, k) => { const d = Math.hypot(p[0] - x, p[1] - y); if (d < bestD) { bestD = d; best = k; } }); return lengths[best]; };
    // Words light up as the wisp reaches them.
    g.textAlign = 'center';
    for (const [text, x, y, hero] of WORDS) {
      const reach = nearest(x * w, (y + .06) * h);
      const shown = !traces || progress >= reach - total * .02;
      g.globalAlpha = shown ? 1 : .18;
      g.font = `${hero ? 900 : 600} ${Math.round(h * (hero ? .12 : .08))}px system-ui, sans-serif`;
      g.fillStyle = hero ? '#ffd23f' : '#f2f2f2'; g.fillText(text, x * w, y * h);
    }
    g.globalAlpha = 1;
    if (!traces) {
      g.fillStyle = 'rgba(255,255,255,.6)'; g.font = `600 ${Math.round(h * .05)}px system-ui, sans-serif`;
      g.fillText('Wisp off: no trails or traced shapes', w / 2, h * .92); return;
    }
    // Tail: the path behind the head, fading out; then the glowing head.
    const tail = total * .35;
    g.lineCap = 'round'; g.lineJoin = 'round';
    for (let d = Math.max(0, progress - tail); d < progress; d += total / 220) {
      const [x1, y1] = at(d), [x2, y2] = at(Math.min(progress, d + total / 220)), f = 1 - (progress - d) / tail;
      g.strokeStyle = `rgba(255,61,127,${.75 * f})`; g.lineWidth = Math.max(1, h * .012 * (.3 + f)); g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
    }
    const [hx, hy] = at(progress), halo = g.createRadialGradient(hx, hy, 0, hx, hy, h * .07);
    halo.addColorStop(0, 'rgba(255,240,250,1)'); halo.addColorStop(.25, 'rgba(255,61,127,.8)'); halo.addColorStop(1, 'rgba(255,61,127,0)');
    g.fillStyle = halo; g.beginPath(); g.arc(hx, hy, h * .07, 0, TAU); g.fill();
    g.fillStyle = 'rgba(255,255,255,.6)'; g.font = `600 ${Math.round(h * .045)}px system-ui, sans-serif`;
    g.fillText(`${framed ? 'line traced in a frame · ' : ''}${shaped} of ${heroes.length} hero words traced with a shape`, w / 2, h * .92);
  }

  // ---- Shared: the font the form asks for, approximated with what the browser has --------------------------------
  const FONT_FALLBACK = { arial: 'Arial, sans-serif', segoe: '"Segoe UI", sans-serif', georgia: 'Georgia, serif', impact: 'Impact, "Arial Black", sans-serif' };
  const WIDE = new Set(['unbounded', 'rubik-mono', 'sixtyfour']), SERIF = new Set(['fraunces', 'abril', 'gloock', 'dm-serif']);
  function font(weight, px, forceStyle) {
    const family = document.getElementById('fontFamily')?.value || 'auto', style = forceStyle || document.getElementById('fontStyle')?.value || 'auto';
    const scale = +(document.getElementById('fontScale')?.value || 1.25);
    const stack = FONT_FALLBACK[family] || (SERIF.has(family) ? 'Georgia, "Times New Roman", serif' : family === 'auto' ? 'system-ui, sans-serif' : WIDE.has(family) ? '"Arial Black", Impact, sans-serif' : 'Impact, "Arial Black", sans-serif');
    const bold = style === 'bold' ? 900 : style === 'regular' ? 500 : weight;
    return `${style === 'italic' ? 'italic ' : ''}${bold} ${Math.round(px * scale / 1.25)}px ${stack}`;
  }
  const LINES = ['Wise men say', 'only fools rush in', 'but I can’t help', 'falling in love with you'];
  const ART = { warm: '#ffb067', ink: '#fff5e6', cool: '#9fd8ff' };

  // ---- Camera, backdrops and geometry -------------------------------------------------------------------------
  const LINE_LOOP = 10, LINE_EVERY = 2.2;
  function lineFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), s = settings();
    const t = (now / 1000) % LINE_LOOP, pan = (s.camera || 'pan') === 'pan', speed = +s.pan_speed || 0;
    const kinds = Array.isArray(s.backdrops) ? s.backdrops : [], rate = +s.backdrop_rate || 0, geometry = +s.geometry || 0;
    scenery(g, w, h);
    g.fillStyle = 'rgba(10,14,30,.42)'; g.fillRect(0, 0, w, h);
    // Floating geometry behind the words: count follows the slider.
    const shapes = Math.round(geometry * 7);
    for (let k = 0; k < shapes; k++) {
      const seed = k * 1.618, x = w * ((seed * .37 + t * .025 * (1 + k % 3)) % 1), y = h * (.15 + .7 * ((seed * .71) % 1)) + Math.sin(t * .8 + k) * h * .03;
      const r = h * (.05 + .05 * (k % 3)); g.strokeStyle = `rgba(255,255,255,${.14 + .06 * (k % 2)})`; g.lineWidth = Math.max(1, h * .005);
      g.beginPath(); if (k % 3 === 0) g.arc(x, y, r, 0, TAU); else { const n = k % 3 === 1 ? 3 : 4; for (let i = 0; i <= n; i++) { const a = t * .3 + TAU * i / n; i ? g.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r) : g.moveTo(x + Math.cos(a) * r, y + Math.sin(a) * r); } }
      g.stroke();
    }
    // Lines land every LINE_EVERY s. Panning: everything drifts left at the pan speed and finished lines fade out.
    // Still: each line builds in the middle, holds, then leaves.
    const drift = pan ? speed * 9 * w : 0, size = h * .11;
    g.textBaseline = 'middle';
    for (let n = 0; n < LINES.length; n++) {
      const born = n * LINE_EVERY, age = t - born; if (age < 0) continue;
      const text = LINES[n], chosen = kinds.length && ((n * 7 + 3) % 10) / 10 < rate ? kinds[n % kinds.length] : null;
      g.font = font(n % 2 ? 800 : 600, size); g.textAlign = 'left';
      let width = g.measureText(text).width;
      if (width > w * .85) { g.font = font(n % 2 ? 800 : 600, size * w * .85 / width); width = g.measureText(text).width; }
      let x, y, alpha;
      if (pan) { x = w * .12 + n * w * .28 - drift * age + w * .3 * (t > born ? 0 : 1); y = h * (.3 + .17 * (n % 3)); alpha = Math.min(1, age * 3) * Math.max(.1, 1 - Math.max(0, age - LINE_EVERY * 1.6) / 2.2); }
      else { const life = Math.min(age, LINE_EVERY); x = w / 2 - width / 2; y = h * .5; alpha = life < .3 ? life / .3 : life > LINE_EVERY - .35 ? Math.max(0, (LINE_EVERY - life) / .35) : 1; if (age > LINE_EVERY) continue; }
      if (x + width < -w * .1) continue;
      g.globalAlpha = alpha;
      const pad = size * .35;
      if (chosen === 'outline') { g.strokeStyle = ART.warm; g.lineWidth = Math.max(1.5, h * .006); g.strokeRect(x - pad, y - size * .62, width + pad * 2, size * 1.24); }
      if (chosen === 'filled') { g.fillStyle = ART.warm; g.fillRect(x - pad, y - size * .62, width + pad * 2, size * 1.24); }
      if (chosen === 'vertical') { g.fillStyle = 'rgba(159,216,255,.85)'; g.fillRect(x - pad * 1.6, y - h * .3, size * .22, h * .6); }
      if (chosen === 'echo') for (let e = 3; e >= 1; e--) { g.fillStyle = `rgba(255,255,255,${.1 * (4 - e)})`; g.fillText(text, x + e * size * .12, y + e * size * .1); }
      if (chosen === 'giant') { g.save(); g.font = font(900, size * 2.6); g.fillStyle = 'rgba(255,255,255,.08)'; g.fillText(text.split(' ').at(-1).toUpperCase(), x - size, y + size * .2); g.restore(); }
      g.fillStyle = chosen === 'filled' ? '#1b1230' : ART.ink; g.fillText(text, x, y);
      g.globalAlpha = 1;
    }
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(0, h * .9, w, h * .1);
    g.font = `600 ${Math.round(h * .05)}px system-ui, sans-serif`; g.fillStyle = '#fff'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    g.fillText(pan ? `panning · ${speed.toFixed(3)}` : 'still camera', w * .02, h * .965);
    g.textAlign = 'right'; g.fillStyle = 'rgba(255,255,255,.7)';
    g.fillText(`backdrops on ${Math.round(rate * 100)}% of lines · ${shapes} shapes`, w * .98, h * .965);
  }

  // ---- Hero glitch, drum impact, pulse and glows ---------------------------------------------------------------
  const GLOW_COLOR = { drums: '255,105,180', other: '255,214,90', bass: '170,120,255' };
  const SMALL = [['when', 'drums'], ['the', 'other'], ['night', 'bass'], ['has', 'drums'], ['come', 'other'], ['and', 'bass']];
  function wordFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), s = settings();
    const t = (now / 1000) % 8, kick = Math.floor(t / BEAT), age = t - kick * BEAT;
    const drum = +s.drum_reactivity || 0, pulse = +s.text_pulse || 0, glows = new Set(Array.isArray(s.glows) ? s.glows : []);
    const glowing = Math.round((+s.glow_words || 0) * SMALL.length), strength = +s.glow_strength || 0, glitch = s.glitch ?? true;
    g.fillStyle = '#0f1830'; g.fillRect(0, 0, w, h);
    const glow = g.createRadialGradient(w * .5, h * .5, 0, w * .5, h * .5, w * .6);
    glow.addColorStop(0, 'rgba(80,110,180,.25)'); glow.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = glow; g.fillRect(0, 0, w, h);
    // Instruments: kicks on the beat, bass a slow swell, guitars and keys a quicker one.
    const hit = { drums: Math.exp(-age * 9), bass: .5 + .5 * Math.sin(t * 2.1), other: .5 + .5 * Math.sin(t * 5.3 + 1) };
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = font(600, h * .085);
    const rowWidth = SMALL.reduce((sum, [text]) => sum + g.measureText(text).width, 0) + h * .07 * (SMALL.length - 1);
    const rowFit = Math.min(1, w * .92 / rowWidth), smallFont = font(600, h * .085 * rowFit);
    g.font = smallFont; const widths = SMALL.map(([text]) => g.measureText(text).width), gapSmall = h * .07 * rowFit;
    let cursor = w / 2 - (widths.reduce((a, b) => a + b, 0) + gapSmall * (SMALL.length - 1)) / 2;
    SMALL.forEach(([text, instrument], k) => {
      const x = cursor + widths[k] / 2, y = h * .72, lit = glows.has(instrument) && k < glowing; cursor += widths[k] + gapSmall;
      const scale = 1 + pulse * .22 * hit[instrument];
      g.save(); g.translate(x, y); g.scale(scale, scale);
      g.font = smallFont;
      if (lit && strength > 0) { g.shadowColor = `rgba(${GLOW_COLOR[instrument]},${Math.min(1, strength * (.35 + .65 * hit[instrument]))})`; g.shadowBlur = h * .08 * strength; g.fillStyle = `rgb(${GLOW_COLOR[instrument]})`; }
      else g.fillStyle = 'rgba(242,242,242,.9)';
      g.fillText(text, 0, 0); g.restore();
    });
    // The hero word: punched by the kicks, torn by the glitch.
    const punch = 1 + drum * .16 * Math.exp(-age * 7) * (kick % 4 === 0 ? 1 : .6);
    const tearing = glitch && ((t % 1.7) < .18);
    g.font = font(900, h * .26); const heroFit = Math.min(1, w * .8 / g.measureText('LOVE').width);
    g.save(); g.translate(w / 2, h * .38); g.scale(punch, punch); g.font = font(900, h * .26 * heroFit);
    if (tearing) {
      const slice = h * .26 / 5, shift = h * .02;
      for (let i = 0; i < 5; i++) {
        const dx = (i % 2 ? 1 : -1) * shift * (1 + (i * 7 + kick) % 3);
        g.save(); g.beginPath(); g.rect(-w, -h * .13 + i * slice, w * 2, slice); g.clip();
        g.fillStyle = 'rgba(255,61,127,.9)'; g.fillText('LOVE', dx - shift * .6, 0);
        g.fillStyle = 'rgba(73,202,255,.9)'; g.fillText('LOVE', dx + shift * .6, 0);
        g.fillStyle = '#fff'; g.fillText('LOVE', dx, 0); g.restore();
      }
    } else { g.fillStyle = '#ffd23f'; g.shadowColor = 'rgba(0,0,0,.5)'; g.shadowBlur = h * .02; g.fillText('LOVE', 0, 0); }
    g.restore();
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(0, h * .9, w, h * .1);
    g.font = `600 ${Math.round(h * .05)}px system-ui, sans-serif`; g.fillStyle = '#fff'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    g.fillText(`${glitch ? 'glitch on' : 'glitch off'} · drums ${Math.round(drum * 100)}% · pulse ${Math.round(pulse * 100)}%`, w * .02, h * .965);
    g.textAlign = 'right'; g.fillStyle = 'rgba(255,255,255,.7)';
    g.fillText(`${glowing} of ${SMALL.length} words glow · ${[...glows].join(', ') || 'no glows'}`, w * .98, h * .965);
  }

  // ---- Font, size and text styles --------------------------------------------------------------------------------
  const STYLE_NAMES = { swiss: 'Swiss', poster: 'Poster', outline: 'Outline + boxed word', cutout: 'Cutout boxes', neon: 'Neon glow', extrude: '3D extrude', split: 'Two-tone split' };
  function typeFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), s = settings();
    let styles = []; try { styles = JSON.parse(document.getElementById('letteringStyles')?.value || '[]'); } catch {}
    styles = styles.filter(name => STYLE_NAMES[name]); if (!styles.length) styles = ['swiss'];
    const which = Math.floor((now / 1000) / 2.4) % styles.length, style = styles[which], fade = Math.min(1, ((now / 1000) % 2.4) * 4);
    scenery(g, w, h); g.fillStyle = 'rgba(10,14,30,.35)'; g.fillRect(0, 0, w, h);
    const art = s.match_art_colors, ink = art ? ART.ink : '#ffffff', accent = art ? ART.warm : '#ff3d7f', box = art ? ART.cool : '#2bd8ff';
    // Poster sets the words in capitals, so they are measured as drawn.
    const words = ['only', 'fools', 'RUSH', 'in'].map(word => style === 'poster' ? word.toUpperCase() : word), key = 2, size = h * .17;
    g.globalAlpha = fade; g.textBaseline = 'middle'; g.textAlign = 'center';
    g.font = font(style === 'poster' ? 900 : style === 'swiss' ? 500 : 800, style === 'poster' ? size * 1.25 : size);
    let widths = words.map(word => g.measureText(word).width), gap = size * .28, total = widths.reduce((a, b) => a + b) + gap * (words.length - 1);
    const lineFit = Math.min(1, w * .88 / total);
    if (lineFit < 1) { g.font = font(style === 'poster' ? 900 : style === 'swiss' ? 500 : 800, (style === 'poster' ? size * 1.25 : size) * lineFit); widths = words.map(word => g.measureText(word).width); gap *= lineFit; total = widths.reduce((a, b) => a + b) + gap * (words.length - 1); }
    let x = w / 2 - total / 2; const y = h * .48;
    words.forEach((word, k) => {
      const width = widths[k], isKey = k === key;
      if (style === 'cutout') { g.fillStyle = isKey ? accent : 'rgba(255,255,255,.92)'; g.fillRect(x - gap * .4, y - size * .55, width + gap * .8, size * 1.1); g.fillStyle = isKey ? '#1b1230' : '#1b1230'; g.fillText(word, x + width / 2, y); }
      else if (style === 'outline') { if (isKey) { g.fillStyle = accent; g.fillRect(x - gap * .4, y - size * .55, width + gap * .8, size * 1.1); g.fillStyle = '#1b1230'; g.fillText(word, x + width / 2, y); } else { g.lineWidth = Math.max(1.5, size * .045); g.strokeStyle = ink; g.strokeText(word, x + width / 2, y); } }
      else if (style === 'neon') { g.save(); g.shadowColor = isKey ? accent : box; g.shadowBlur = size * .5; g.lineWidth = Math.max(1.5, size * .05); g.strokeStyle = isKey ? accent : box; g.strokeText(word, x + width / 2, y); g.strokeText(word, x + width / 2, y); g.fillStyle = '#fff'; g.fillText(word, x + width / 2, y); g.restore(); }
      else if (style === 'extrude') { for (let d = 8; d >= 1; d--) { g.fillStyle = `rgba(40,20,60,${.9 - d * .06})`; g.fillText(word, x + width / 2 + d * size * .02, y + d * size * .02); } g.fillStyle = isKey ? accent : ink; g.fillText(word, x + width / 2, y); }
      else if (style === 'split') { g.save(); g.beginPath(); g.rect(x - 4, y - size, width + 8, size); g.clip(); g.fillStyle = ink; g.fillText(word, x + width / 2, y); g.restore(); g.save(); g.beginPath(); g.rect(x - 4, y, width + 8, size); g.clip(); g.fillStyle = isKey ? accent : box; g.fillText(word, x + width / 2, y); g.restore(); }
      else if (style === 'poster') { g.fillStyle = isKey ? accent : ink; g.fillText(word, x + width / 2, y); }
      else { g.fillStyle = isKey ? accent : ink; g.fillText(word, x + width / 2, y); }
      x += width + gap;
    });
    if (style === 'swiss') { g.fillStyle = accent; g.fillRect(w / 2 - total / 2, y + size * .62, total * .3, Math.max(2, size * .05)); }
    g.globalAlpha = 1;
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(0, h * .9, w, h * .1);
    g.font = `600 ${Math.round(h * .05)}px system-ui, sans-serif`; g.fillStyle = '#fff'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    g.fillText(`${STYLE_NAMES[style]} · ${which + 1}/${styles.length}`, w * .02, h * .965);
    g.textAlign = 'right'; g.fillStyle = 'rgba(255,255,255,.7)';
    const family = document.getElementById('fontFamily'); const name = family?.selectedOptions[0]?.textContent || 'font';
    g.fillText(`${name} · ${Math.round(+(document.getElementById('fontScale')?.value || 1.25) * 100)}%${art ? ' · colours from the art' : ''}`, w * .98, h * .965);
  }

  // Cinematic illustration mode (render/layout.py illustration_layout): on, each picture gets a large panel at the
  // left, right or centre with the lyrics beside or below it; off, a small picture sits at one side and the lyrics
  // take most of the frame. The frame cycles through the positions.
  // The caption lives under the frame (#cinematicNote) so the picture stays clean.
  const CINEMA_NOTES = {
    on: 'Cinematic on: each illustration fills a large panel at the left, right or centre, the lyrics beside or below it.',
    off: 'Cinematic off: a small picture sits at one side and the lyrics take most of the frame.',
    fullscreen: 'Full-screen artwork: the painting covers the frame and each scene keeps a calm area at one side for the lyrics. Cinematic mode does not apply.',
    verse: 'Verse backgrounds: a full-bleed painted scene for each lyric group, with calm space kept for the lyrics. Cinematic mode does not apply.',
    matte: 'Greenscreen scenery: the horizon fills the lower part, the sky is flat green for keying and the lyrics sit in it. Cinematic mode does not apply.',
  };
  function cinemaFrame(canvas, now) {
    const [w, h] = fit(canvas), g = canvas.getContext('2d'), on = document.getElementById('cinematic')?.checked !== false;
    const layout = document.getElementById('artworkMode')?.value || 'cutout';
    let art, text, tick = Math.floor(now / 2600), note;
    if (layout === 'fullscreen' || layout === 'verse') {  // render/layout.py: full-bleed art, the text at one side
      const sides = [[.06, .2, .46, .6], [.48, .2, .46, .6], [.12, .06, .76, .34], [.12, .6, .76, .34]];
      art = [0, 0, 1, 1]; text = sides[tick % sides.length]; note = CINEMA_NOTES[layout];
    } else if (layout === 'matte') {  // scenery below the skyline, flat green sky above it holding the lyrics
      art = [0, 0, 1, 1]; text = [.06, .05, .88, .44]; note = CINEMA_NOTES.matte;
    } else {
      const boxes = on ? [[[0, .02, .48, .96], [.5, .04, .48, .92]], [[.52, .02, .48, .96], [.02, .04, .48, .92]], [[.15, .01, .7, .7], [.04, .74, .92, .24]]]
                       : [[[.07, .19, .26, .62], [.38, 0, .58, 1]], [[.67, .19, .26, .62], [.04, 0, .58, 1]]];
      [art, text] = boxes[tick % boxes.length]; note = CINEMA_NOTES[on ? 'on' : 'off'];
    }
    const noteBox = document.getElementById('cinematicNote'); if (noteBox && noteBox.textContent !== note) noteBox.textContent = note;
    const bg = g.createLinearGradient(0, 0, w, h); bg.addColorStop(0, '#1b2140'); bg.addColorStop(1, '#3a2a4a');
    g.fillStyle = bg; g.fillRect(0, 0, w, h);
    const [ax, ay, aw, ah] = [art[0] * w, art[1] * h, art[2] * w, art[3] * h];
    g.save(); g.beginPath(); if (layout === 'cutout') g.roundRect(ax, ay, aw, ah, h * .03); else g.rect(ax, ay, aw, ah); g.clip(); g.translate(ax, ay); scenery(g, aw, ah);
    if (layout === 'matte') { g.fillStyle = '#19e619'; g.fillRect(0, 0, aw, ah * .56); }
    else if (layout !== 'cutout') { g.fillStyle = 'rgba(10,14,30,.25)'; g.fillRect(0, 0, aw, ah); }
    else if (on) { const glow = g.createRadialGradient(aw * .3, ah * .3, 0, aw * .3, ah * .3, aw * .8); glow.addColorStop(0, 'rgba(255,220,160,.35)'); glow.addColorStop(1, 'rgba(0,0,0,.35)'); g.fillStyle = glow; g.fillRect(0, 0, aw, ah); }
    g.restore();
    const [tx, ty, tw, th] = [text[0] * w, text[1] * h, text[2] * w, text[3] * h];
    if (layout !== 'cutout' && layout !== 'matte') { g.fillStyle = 'rgba(8,10,24,.28)'; g.beginPath(); g.roundRect(tx, ty, tw, th, h * .03); g.fill(); }
    g.fillStyle = layout === 'matte' ? '#1b1230' : 'rgba(255,255,255,.95)'; g.textAlign = 'left'; g.textBaseline = 'top';
    const big = Math.min(th * .32, tw * .16); g.font = font(900, big); g.fillText('SUNLIGHT', tx + tw * .04, ty + th * .12);
    g.fillStyle = layout === 'matte' ? 'rgba(27,18,48,.55)' : 'rgba(255,255,255,.55)';
    for (let k = 0; k < 3; k++) { const y = ty + th * .12 + big * 1.3 + k * big * .42; if (y + big * .22 > ty + th) break; g.fillRect(tx + tw * .04, y, tw * (.9 - .18 * ((k + tick) % 3)), big * .22); }
  }

  const sims = [['beatSim', beatFrame], ['wispSim', wispFrame], ['lineSim', lineFrame], ['wordSim', wordFrame], ['typeSim', typeFrame], ['cinematicSim', cinemaFrame]];
  const visible = new Set();
  const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const entry of entries) entry.isIntersecting ? visible.add(entry.target) : visible.delete(entry.target);
  }) : null;
  function loop(now) {
    for (const [id, draw] of sims) {
      const canvas = document.getElementById(id);
      if (!canvas || !canvas.clientWidth || (observer && !visible.has(canvas))) continue;
      try { draw(canvas, reduced ? 1600 : now); } catch (error) { console.warn('[fx-sim]', error); }
    }
    requestAnimationFrame(loop);
  }
  function start() {
    for (const [id] of sims) { const canvas = document.getElementById(id); if (canvas && observer) observer.observe(canvas); }
    requestAnimationFrame(loop);
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();
