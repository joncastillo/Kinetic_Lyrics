# Effects review: bring every entrance and exit effect to 95

The user asked for every curated entrance and exit effect (`assets/particles/entrance/*.json`, `assets/particles/exit/*.json`)
to be judged and improved until each scores at least **95 overall**. Clone groups are to be kept, but each
effect in them must be made clearly distinct (the user chose "keep all, make distinct"). Every effect must also
stay colourable by the AI (see "Colour" below). This file is the handoff for that work. Several sessions can
run in parallel, one per workstream below. Read `AGENTS.md` and `RUBRIC.md` in this folder first.

## Status (2026-11-03)

- **Kinetic entrances (12): done.** All 95+; see `LEDGER.md`.
- **Letters-spin (7) and petal exits (5): done.** All twelve pass 95 overall (Session A).
- **The other entrances and exits: in progress.** Glass is being rebuilt (Session B), materials (Session C) and ornament, smoke and cinematic (Session D).

| Group | Code | Judged grades (impressiveness) |
|---|---|---|
| letters-spin entrances (7) | `src/effects/kinetic/letters.py` | spiral 95, above 92, below 92, diagonal 92, left 92, right 91, scatter 89 (rounds e19-e24) |
| petals exits (5) | `src/effects/particles/petal_exits.py` | scatter 95, whirl 93, fall 92, gust 91, flutter 91 (rounds x17-x22) |
| glass and chrome entrances (6) | `src/effects/particles/glass_fx.py` | sweep 89 (passes: overall 95.4), assemble 85, mosaic 78, prism 76, spiral 74, liquid-chrome-assembly 73 (round g24; a fresh, harsher judge than e1) |
| glass and chrome exits (6) | `src/effects/particles/glass_fx.py` | shatter 83, impact 83, liquid-chrome-collapse 79, cascade 78, fan 76, vortex 75 (round g24) |

Overall (0.4 x judged + 0.2 x measured smoothness, consistency, uniqueness), all passing 95:

| Effect | Judged | Smooth | Consistent | Overall |
|---|---|---|---|---|
| letters-spin-above | 92 | 100 | 100 | 96.8 |
| letters-spin-below | 92 | 100 | 100 | 96.8 |
| letters-spin-right | 91 | 97.7 | 100 | 95.9 |
| letters-spin-spiral | 95 | 88.2 | 100 | 95.6 |
| letters-spin-diagonal | 92 | 93.9 | 100 | 95.6 |
| letters-spin-left | 92 | 93.8 | 99 | 95.4 |
| letters-spin-scatter | 89 | 98.3 | 100 | 95.3 |
| petals-scatter | 95 | 99.2 | 100 | 97.8 |
| petals-fall | 92 | 100 | 100 | 96.8 |
| petals-flutter | 91 | 95.6 | 100 | 95.5 |
| petals-whirl | 93 | 89.7 | 100 | 95.1 |
| petals-gust | 91 | 93.7 | 100 | 95.1 |

Several are close to the line; the judges' last notes below are the next improvements if anyone revisits them.

**Smoothness and flicker.** `score.py` counts a pixel that blinks on and off more than once as flicker. A
letter sliding across the screen does that through the gaps between its strokes, and an orbit revisits the
same pixels. A single solid shape sweeping past costs nothing. So the fixes that worked were solid shapes
behind moving letters: a wheel disc (left, 81 -> 94), a solid accent ribbon (diagonal, 82 -> 94). Shorter paths
help a little; removing decorations usually does not. Two more costs to check first: **a pop** (a big shape
on screen in the first frame: grow it in), and **a motion that reverses** (an overshoot past upright, a squash
pulse): pixels at the edge are crossed twice. Removing both, and reversing the relay so tiles fall over letters
that have not stood yet, took right from 81 to 98. `metrics.json` splits each case into `pop` and `flicker`;
read it before guessing.

Latest judge notes (Session A, if revisited):
- spiral: give the riders letterform play of their own (a squash or edge-on turn at the ring's sides), or a second accent tint.
- petals whirl: lighten the near-arc rose a step on paper so tonight's wreath is even.
- right: lay the waiting tiles out as a clean end-to-end row so they never overlap (watch smoothness).
- above: a hard-edged darker back face or short extrusion while edge-on.
- below: finish the gold-to-plain hand-over by .8.
- left: space the wheels about a disc-width apart while rolling.
- diagonal: the ribbon's tail retracting in visible steps as each letter lands.
- scatter: cap the stretch at about 1.3x throughout.
- petals fall: leave the plume alone; at most a separate 3-4 petal flourish looping in clear background.
- petals gust: cap the crest's height on every word so MOVE and Starlight stay in frame.
- petals flutter: lead the three big petals a petal width clear of the cluster.

### Session D (ornament, trees, petal/ink/thread letterings, cinematic, smoke exits)

| Group | Code | Judged grades (impressiveness) |
|---|---|---|
| smoke exits (1) | `src/effects/particles/smoke_exits.py` | wisp 72 (round dx11); billow, evaporate, vortex and plume removed at the user's request (2026-11-03) |
| cinematic (4) | `src/effects/particles/ember_prism.py` | prismatic-singularity 78, ember-forge 70, ember-ash-drift 68, prismatic-helix 65 (rounds c1-c2) |
| ornament letterings (11) | `src/effects/growth/crafted.py`, `ornaments.py`, `inked.py` | folded-paper 73, brocade 67, cross 66 (round d4); gold-filigree 64, clockwork 64 (round d3); ink-bloom 67 (p7, ink in water), bamboo 64 (p8, letters shoot up joint by joint), coral 65 (p8); obsidian 63 (d9, now a geode), thread-stitch 62 (d9, cross-stitch), pearl-lace 59 (d8) on the stricter judge |
| trees and garden (4) | `arboreal.py`, `garden.py` | succulent-garden 66, meadow-grass 65 (p6, now turf with a gust sheen), autumn-maple 58 (d8), old-oak 56 (d7) on the stricter judge; fresh judge e3: autumn-maple 79, old-oak 79 (crown spans the word, clumps pop in autumn orange), catholic-cross 76 (x2: gold leaf swept across each letter, cross flares per letter) |
| petal letterings (4) | `src/effects/growth/blossom.py` | rebuilt (p3-p4): petals-breeze 69, petals-wind 68, petals-spiral 68, petals-grow 68 on the stricter judge |

Judge calibration (2026-11-03, blind): three effects with ledger grades were mixed unlabelled with three
Session D effects and graded by the Session D judge and by a brand-new judge. Ledger 93 / 89 / 78
(kinetic-pop-extrude, glass-sweep, glass-mosaic) scored 76 / 71 / 59 and 78 / 69 / 59: both judges agree within
2 points and sit a steady 15-20 points below the ledger, because runs/ref/ (the 95-100 anchor sheets) is
missing. The long-running Session D judge also rates Session D effects about 6 points above a fresh judge
(familiarity). Grades below are raw, on today's scale; they are not adjusted.

Fresh-judge baseline (2026-11-03, with runs/ref anchors): ember-ash-drift 77, gold-filigree 75, prismatic-helix 72,
smoke-wisp 71, clockwork 69, folded-paper 69, ember-forge 66, catholic-cross 65, smoke-evaporate 65, jeweled-brocade 63,
smoke-plume 60, smoke-billow 59; succulent-garden 67 (window box), autumn-maple 64, old-oak 58.

Round d5-d6 used a fresh judge that grades 6-14 points below the earlier ones (asked to compare old and new
renders side by side, it preferred the new old-oak, maple and singularity each time, so the lower numbers are
calibration, not regressions). On that scale: petals-wind 66, prismatic-singularity 64, smoke-vortex 61.
Pearl lace is now pearls strung round each letter's outline on a deep satin body (a colour per word) with swags
that swing under the baseline; succulent garden drops its letters into a soil bed, where jade rosettes twist open.

The judges' standing notes: every lettering needs its own letter transformation rather than a shared
bottom-up grow; maple and oak are near-duplicates, as are petals-breeze and petals-wind, and meadow and
succulents share a reveal; the petal letterings need a crisp letter mask with a solid base so they read at
rest. Concept changes have moved grades by 4-8 points a round; polish alone moves them by 1-2.

### Session C (material entrances and exits)

| Group | Code | Judged grades (impressiveness) |
|---|---|---|
| material entrances (8) | `src/effects/materials/recipes/` | lava-flow-fill 77, ice-block-thaw 76, branding-iron-scorch 75, neon-tube-ignite 72, mucha-silk-lettering 72, architectural-sketch 69, stained-glass-leading 67, moss-overgrowth 65 (rounds m4 to m14; new judges from m5 and m11) |
| material exits (10) | `src/effects/materials/recipes/` | freeze-shatter 91 (95.4 overall: passes), thermite-burn 78, neon-burnout 76, rust-corrode-crumble 74, dust-disintegrate 73, paper-burn 72, acid-dissolve 69, lightning-vaporize 67, steam-evaporate 66, silk-veil-unveil 65 (rounds mx4 to mx18; new judges from mx5 and mx11) |

**Where the judge and the metrics pull apart (rounds 23 to 28).** Changes the judge rewards can cost more on the measured side than they gain: dust's lingering, spreading clouds were judged 78 but measured as too like steam (uniqueness 78-90, smoothness 91-96), 85.8-88 overall against 90.3 for the plain rising dust; neon-burnout's afterimage is judged 77-78 but adds alpha after the word has gone, which the smoothness metric counts as flicker (93.6 to 88.5), so it is level overall. Measure every change before judging it. Dust (90.3) needs judge 88 with its current metrics; neon-burnout (88.5) needs 91.

**Measured overall, rounds 18 to 22 (0.4 x judge + 0.2 x measured).** Freeze-shatter 95.4 (passes). Closest after it: dust-disintegrate 89.4 (judge 75; needs about 88), neon-burnout 88.4 (77, smoothness 88 since its afterimage), lava-flow-fill 87.9, ice-block-thaw 87.5, thermite-burn 87.4 (uniqueness 82, nearest rust), paper-burn 87.2, lightning-vaporize 86.1, rust 86.0, silk veil 85.8, acid 85.6, steam 85.3, branding iron 84.4 (smoothness 74: the slam is a pop), stained glass 81.6, neon ignite 79.5 (uniqueness 65), moss 79.1 (uniqueness 65), architectural sketch 77.2 (uniqueness 48, nearest luminous coral). Measured parts are mostly near 100, so the gap is the judge grade: 12-20 points each. Round 22 (a third judge, about the same scale): dust 75 with a gust lean before it breaks, neon burnout 77 with a complementary afterimage, brand 76.

**Rounds 15 to 18: freeze-shatter passes (impressiveness 91; smoothness 95.1, consistency 100, uniqueness 100; 95.4 overall).** What lifted it from 86: a thick crack web held at full strength from .42 up to the split over darkened ice, fewer and larger pieces that keep recognisable letter fragments and rotate as they tumble, and, the decisive beat, a frozen-time hang: after the crack the pieces part by a hair and hang still for a couple of frames (the word still readable as a mosaic), then burst. The judge would push it further with a three-tile hang, a 1-2 px drift on its last frame, a final accent at the tail and darker shards on cream. Lightning 67: the vapour front and radial sparks do not read yet; it needs bold branched bolts and a hard-edged expanding ring from each strike point.

**Round 14.** Measured again for the first time since round 4: freeze-shatter smoothness 96.8, consistency 100, uniqueness 100, so with impressiveness 86 it is 93.8 overall and needs 89 to pass; thermite-burn 98.7, 100, 70.9 (nearest rust-corrode-crumble), 85.1 overall. Steam is redesigned (66, from 61): condensation, then each letter peels upward in a relay; the tongues should become a few smooth S-curling wisps and the beads are not yet visible. Silk entrance 72 and veil 65 hang from gold pins and the veil holds satin only briefly; both need shaped, swinging hems, bigger pins and stronger satin contrast, and the veil its own motion (blown sideways). Rust 74 scatters its slabs sideways; they should be bigger and fall about half a word height. The freeze crack web is still too fine to see: 3-5 thick branches held for two frames.

**Round 13.** Freeze 86 (the outward kick reads; next a one- or two-frame bright fracture web at .45). Brand 75 (the stamp needs to be about 25 % flatter for two frames with an overshoot, plus a pressed bite mark). Rust 73 (the grey stage is gone; the heap must show 3-6 distinct slabs per letter). Neon 72 (the surge reads; on cream the settled tube needs a saturated filled core). Acid 69 (long drips; they should be opaque with heavy beads, olive-black on cream). Moss 65 (flat shading and pink flowers; next a few large clean clumps and 3-5 big blossoms per word). Silk veil 64 is now the satin entrance run backwards; its satin hold should shorten to about .15 and each banner should billow and curl as it peels off to a drawn gold pin.

**Rounds 11 and 12 (a fresh judge, about 1-3 points tougher than the last; the 95-100 reference sheets are gone, so it calibrates on kinetic-pop-extrude as the 93 anchor, copied to runs/anchor/).** Freeze-shatter 85: bigger faceted pieces, a jolt and swell before the break; next a one-frame crack flash and more outward spin. Brand 74: the grey ring is gone, a crisp slam, a warmer amber char; next a squash-and-stretch stamp and a bright rim to 1.0. Rust 72 collapses top-down into a heap of saturated rust (no longer like freeze); the grey steel stage at .2-.4 should go and the slabs should stay chunks as they land. Acid 67 slumps into drips from .45; the drips should be fat and opaque. Neon 70: the surge at .47 is too faint; make it a 2-3 frame near-white flash and fill the cyan on cream. Moss 62 now climbs from the baseline in tendrils, but its fill looks like photo grass: it needs flat two- or three-tone graphic moss, curling tendrils and visible flowers.

**Round 10.** Acid-dissolve is redesigned (66, from 59): acid beads land along the top of the word, then run down eating channels with an etched rim until only lace is left, and drip below; it is no longer a near-clone of rust. It next needs bigger glossy beads that swell before they run, wandering blobby channels (they read as a striped wipe) and a dark green-black stain instead of olive on warm letters. Neon ignite 70: the draw-on now works; it wants a two-tone glow, a deeper cyan on cream and one late stutter. The brand 73 ends on a clean char and needs a wider ember rim on navy. Silk 71: the pendulum swing still cannot be seen and the folds read as pleated card. Freeze 84: the white crack flare reads, the shudder does not (make it 2-3 px or a scale pulse). Rust 70: the slabs fall, but release should start by .5 with clean gaps between pieces.

**Round 9.** Freeze-shatter 83 (a radial burst, dark piece edges); it next needs a 2-3 frame shudder and a bright forking crack at .45-.55 so the first half is not static. Lava 77 (ash crust) wants a cool ash body with thin orange seams and a crisp outline. Brand 71 (the smoky ring now rolls out) still ends on speckled grain: the last 30 % needs a solid dark char with a thin ember rim. Silk 70 (one dye per word, swallowtail hems) reads as crumpled foil: two or three broad soft folds and one wide highlight, and a visible hem pendulum. Rust 68 breaks into slabs; they must release by .5 and fall half to one word height by .85. Neon ignite 66 traces each tube before it strikes, but the letter must stay hidden until the tip draws it, with a bigger glowing tip and a dark glass casing for cream. Note on strips: tile k is progress k/18, and the host fades every exit from .88, so the last three tiles are always empty.

**Round 8.** Freeze-shatter now breaks the frozen letters along their cracks into big ice pieces that tumble and fall (81); the judge wants a visible radial kick from the impact point and darker piece edges for cream. Art Nouveau silk folds is a new painter (66): satin banners drop from pins over each letter, draw in to satin letters, then an ink contour and a sheen; it needs one or two colours per word, a swinging swallowtail hem and a bolder contour. Lava (76) needs a lighter ash-grey crust for dusk and a splash where each pour lands. Rust (66) should break into solid slabs that fall from .55 to .95, like the ice pieces. silk-veil-unveil keeps the old cloth simulation.

**Next for the material family (judge, rounds 5 to 7).** Branding iron and lava are no longer near-clones (round 7): the brand hangs large, slams down squashed in a white flash at .2 and springs back, and the lava pours down each letter in turn with drips ahead. The brand next needs a clean finish (a dark char body with a thin ember outline instead of all-over grain) and a scorch ring or smoke puff spreading from the slam; the lava needs fewer, coarser cracks that keep the counters and thin strokes whole, and a bigger first pour. Neon ignite needs each tube to trace along its stroke before it lights. Moss needs lighter tips and to grow from the baseline as tendrils. Freeze-shatter needs fewer, bigger shards (about a third of the letter height) that fly from a crack point and fall about a word height. Rust still crumbles too late (about .7) and should drop 4-6 px chunks from .55. Acid and rust both change texture in place and then fade as grains.

**Next for the material family (judge, round 4).** Nothing is above 76; to reach 85 each effect needs a second transformation that lasts at least three frames. Branding iron and lava have converged (both hot-to-dark left-to-right reveals with glowing seams): give the brand a visible iron or glow bar pressing each letter and a sharp embossed char, and the lava a black basalt crust with 2-3 px bright cracks that dim letter by letter. Changes the judge still could not see: neon ignition flash (needs about 1.5x final brightness), acid splash blobs and rim (make them larger than the stroke and dark brown), dark dust on paper, rust pits (near black, larger than the stroke, alone for three frames), stained-glass glints, and long dark cracks on freeze-shatter.

**Beats shorter than a frame cannot be seen.** At 0.6 s an effect is 18 frames, so one frame is about 0.056 of progress. In round 3 several beats were narrower than that (a 0.012-wide pop, a 0.03 crack window) and the judge reported "no visible change" for them. Give every beat at least 0.1 of progress (two or three frames).

**Material look-alikes removed (2026-11-03, the user's call).** The round-2 judge named near-clone pairs in the
material family, and the user asked for the look-alikes to be removed rather than made distinct. In each pair the
lower-graded effect went: marble-chisel-reveal (kept ice-block-thaw), cathedral-stained-glass (kept
stained-glass-leading), bioluminescent-bloom (kept moss-overgrowth), snow-blown-away and sandstone-crumble (kept
dust-disintegrate), petrify-crumble (kept rust-corrode-crumble), ice-sublimate (kept acid-dissolve),
mucha-silk-unfurl (kept silk-veil-unveil), ink-in-water (kept steam-evaporate). Their recipes, painters,
descriptions, colours and palettes are gone, and two scenes (crystal-and-coral, golden-ornament) no longer list
them. The first-pass grades below still name them for the record.

**Material rework so far (Session C, rounds m2/mx2 then m3/mx3).** Most effects finished their motion by half way
and held still; the reworks give each a second beat over the back half: the ice block's
fissures that trace the letters before a left-to-right thaw, the brand rolling on from the left with an ember rim,
lava as saturated orange with glowing seams, neon's filled tubes and wider halo, moss overgrowing then pulling back,
big Tiffany panes with thick foil and solder, a crack network before freeze-shatter bursts, acid splashes that eat
holes outward, a violet charge and dark rim on lightning so it reads on paper, a pop before each neon tube dies,
a ragged white-hot thermite edge with slag and drips, and steam that ripples first and peels later.

### First-pass grades of everything else (round e1/x1, untouched since)

**Entrances**
- (glass and liquid chrome: rebuilt, see the table above)
- ice-block-thaw 74, architectural-sketch 72, lava-flow-fill 72, autumn-maple-lettering 70
- ember-forge 66, cathedral-stained-glass 66, clockwork-lettering 64
- branding-iron-scorch 62, gold-filigree-lettering 62
- bioluminescent-bloom 60, catholic-cross-lettering 60, folded-paper-lettering 60, jeweled-brocade-lettering 60
- bamboo-lettering 58, frost-crystal-lettering 58, luminous-coral-lettering 58
- ink-bloom-lettering 55
- Not yet judged (the e1 batch rendered them; see `runs/e1/`): marble-chisel-reveal, meadow-grass-lettering,
  moss-overgrowth, mucha-silk-lettering, neon-tube-ignite, obsidian-lattice-lettering, old-oak-lettering,
  pearl-lace-lettering, petals-breeze-lettering, petals-grow-lettering, petals-spiral-lettering,
  petals-wind-lettering, prismatic-helix, stained-glass-leading, succulent-garden-lettering, thread-stitch-lettering.

**Exits**
- prismatic-singularity 76, freeze-shatter 76, paper-burn 75, neon-burnout 74, rust-corrode-crumble 73
- dust-disintegrate 72, petrify-crumble 72
- (glass and liquid chrome: rebuilt, see the table above)
- sandstone-crumble 68, ember-ash-drift 66, silk-veil-unveil 64, mucha-silk-unfurl 62
- lightning-vaporize 62, ice-sublimate 58, acid-dissolve 55, ink-in-water 55, smoke-wisp 55
- Not yet judged (rendered in `runs/x1/`): smoke-billow, smoke-evaporate, smoke-plume, smoke-vortex,
  snow-blown-away, steam-evaporate, thermite-burn.

### Recurring problems the judges found

- **Dead time.** Nothing visible for the first 40-50% of an entrance; the motion is then crammed into a few frames.
- **Near-clones.** The glass entrances and exits, the textured-fill letterings (filigree, brocade, coral), and
  similar material crumbles.
- **Colour that fails on one background.** Pale, blurred or desaturated colour goes muddy on dusk or vanishes
  on paper.
- **No beat before the break-up (exits).** There is no crack, swell or pause before the word comes apart.
- **To pass about 88, one memorable moment per effect.** Polish alone stalls in the mid-80s; each effect needs a
  signature beat that is visible in at least two sampled moments, then graphic craft (shading, shape variety).

## Workstreams for parallel sessions

Each session owns its files outright. New painters go in a new module per family, wired in with one entry in
`FAMILY_PAINTERS` in `src/effects/particles/motion.py` (that dict is the only shared line; on a rebase conflict,
keep both entries).

| Session | Owns | Effects |
|---|---|---|
| **A** | `effects/kinetic/letters.py`, `effects/particles/petal_exits.py`, the draft scenes | Finish letters-spin (7) and petals exits (5). Judge the two draft scenes (`render/poster/register.py`, `drop.py`, scene files kept in `automation/kinetic-effects-lab/drafts/`: copy them into `assets/scenes/` to work on them, and back out before saving goldens until they pass). Then the remaining scene jerk work (see "Scenes"). |
| **B** | `effects/particles/glass_fx.py` | Glass: entrances glass-assemble, -mosaic, -prism, -spiral, -sweep, plus liquid-chrome-assembly; exits glass-cascade, -fan, -impact, -shatter, -vortex, plus liquid-chrome-collapse. All twelve now live in `glass_fx.py` (the chrome recipes were moved to the glass family to route there); the old shared fragment painter in `motion.py` no longer serves them. See "Glass family notes" below. |
| **C** | `effects/materials/` (recipes and `fx.py`) | Material family: 8 entrances and 10 exits after the look-alikes were removed (burns, crumbles, dissolves, frost, lava, neon, glass, silk, sketch: `family: material`). |
| **D** | ornament, growth, cinematic, smoke | Ornament letterings (11), trees (2), petals/ink/thread letterings (`hold: particles`), cinematic (3 entrances, 3 exits), smoke exits (1, wisp). |

## Glass family notes (Session B, rounds g1-g24)

- **Mechanism.** `glass_fx.py` cuts the word into facets (a Voronoi split, a spider web of cracks from an impact
  point, or whole letters found from the gaps between columns of ink) and gives each a coloured glass face with a
  dark inner rim and light outer rim. The glass colour is a saturated mid-tone stepped by the word's seed, so
  neighbouring words differ and the facets hold on cream. Relays run letter by letter. Liquid chrome is a
  metaball field (blurred discs, thresholded) with silver mirror shading and a single thin dark horizon.
- **What the judge rewarded (g3 -> g4, +4 to +13 each).** Per-word saturated colour with a dark rim; scatter
  capped at about 1.5 word heights; letter-by-letter relays; whole letters (not slivers) for the fan and the
  sweep; no half-transparent ghosts; in-plane tilts instead of y-flips (mirrored letters read as a bug); a flash
  masked to the word's own pixels rather than a glow disc (a glow changes alpha and fails the readability test).
- **Still needed, per the g24 judge (73-89; sweep passes).** Four effects now show a second beat (sweep's ink relay, mosaic's
  pop, vortex's ring, cascade's floor) but the beats are small next to the arrival or the break; three exits still
  end on one whole letter drifting alone (shatter's and impact's last letter, the fan's last letter); facets on the
  nine-letter word are slivers (floor the facet size at a quarter letter height); nothing yet has the hard-edged
  poster confidence of the reference. Specifics: assemble's swell is invisible (make it 1.15x over two frames or
  drop it); mosaic's rock should be 8-10 degrees; prism must hold waiting facets beside or above the word, never
  below, and the green fringe reads as an RGB glitch; spiral's loop is an arch standing 1.5 word heights, tilt it
  across the baseline and shrink it; sweep's highlight needs a drawn white bar and a fuller pane on cream; chrome
  assembly needs a beat in 0.6-0.82 and a less stock gradient; shatter and impact must break the last letter by
  frame 10; cascade's bounce is invisible; the fan's tangent flick must travel half a letter; vortex's turning word
  must stay in frame and the ring should be an edge-on ellipse; chrome collapse loses MOVE's counters at 0.33.
- **Pitfalls.** Pillow's GaussianBlur on a transparent RGBA disc bleeds black at the edge and shows the canvas as a
  grey square: build glows with numpy. ImageEnhance.Brightness scales alpha too: shade with a point table on the
  RGB bands. A whole-word twist or scale of more than about 3 degrees or 3% at the 0.15 mark fails the exit
  readability test.

## The loop for each effect

1. **Render and measure.**
   - Entrances: `& $py automation/kinetic-effects-lab/tools/score.py automation/kinetic-effects-lab/runs/<round> <id> [...]`.
   - Exits: set `$env:PHASE='exit'` first. Use a fresh round folder per round (`e9`, `x10`, `g1`, ...).
   - `$py` is `C:/dev/projects/Kinetic_Lyrics/.venv/Scripts/python.exe`.
   - Each effect gets `<id>.png` (three words at ten moments), `<id>-strip.png` (every frame), `.gif`, `.mp4`,
     and `metrics.json` (smoothness, consistency, uniqueness).
2. **Look at the sheet yourself** before judging, and fix obvious problems (`Read` the PNG).
3. **Judge.** Use a general-purpose subagent that never reads source code.
   - Brief it from `JUDGE.md` and the anchors in `RUBRIC.md`: fade 20, slide-in 35, After Effects preset 70,
     studio title 85-90, references 95-100.
   - Give it the previous grades and one passing reference to calibrate against
     (`runs/r40m/kinetic-pop-extrude.png` = 93).
   - Ask for: effect | previous | now | single highest-impact change still needed.
   - Reuse the same judge across rounds while its context is small. Start a fresh one, with the previous grades as
     anchors, once it grows past about 200k tokens.
4. **Apply the most impactful changes, and repeat.** `overall = 0.4 x impressiveness + 0.2 x (smoothness +
   consistency + uniqueness)`, so an effect with clean measured scores passes at an impressiveness of about 88.

## Rules and pitfalls learned so far

- **Entrances.**
  - Something on screen from the first frames (grow in, never pop).
  - Opaque, not half-transparent fades.
  - Within about a word height or two of the word.
  - Readable by 85%.
  - The last frame is exactly the plain word (or, for `grow` / `hold: particles` letterings, the decorated word).
- **Exits.**
  - The first frame is exactly the plain word.
  - Still readable at 15%.
  - Nothing left at the end.
  - Petals, shards and the like should dissolve over the last part, staggered, not vanish in one frame.
- **Measuring.** For particle and material families, spill beyond the word is allowed (recorded, not deducted).
  Kinetic type keeps the spill rule.
- **Decorated letterings are measured against their held word.** `score.py` used to compare every entrance's
  last frame with the plain sprite, so every `grow` / `hold: particles` lettering lost 30 points for "final
  frame differs" and more for the approach, and sat at 0-45 consistency whatever it looked like (see the
  e1 metrics). Since round m2 it compares them with the frame at progress 1 (the held, decorated word). If
  you have consistency grades for decorated letterings from before that, re-measure.
- **Remove `assets/particles/pacing.json` entries** for an effect you rebuild: they re-time the old effect and would
  distort yours.
- **Draw the word's drop shadow too.** The renderer's word sprite carries a soft shadow, and it is in the sprite's
  alpha. Break-ups must include it (alpha > 0), or a dark ghost of the word stays to the end. Take the word's
  colour from solid pixels only (alpha > 220), or blends start grey.
- **Flights that all end on the last frame converge into a clump.** Time travel by time since leaving instead.
- **Colours that hold on navy and cream alike** are saturated mid-tones. Never choose dark tones just because the
  word is light.
- **ruff reformats long lines.** Patch scripts that match exact text break after a format. Match the formatted
  text, use `Edit`, or re-read the file before patching.
- **The worktree guard rejects complex Bash.** Put Python in a scratchpad script file, and run git commands
  separately.

## Colour (the AI colours every effect)

- **How a colour reaches the effect.** The AI effect director (`src/direction/effects.py`) chooses a colour for
  each line's effect, carried as an id like `glass-mosaic@#3fa9ff`. `EffectCatalog` in
  `effects/particles/catalog.py` resolves that to the effect with `color` set.
- **How the effect is recoloured.** `paint_transition` recolours any effect by a gradient map (black -> colour ->
  white, `effects/colorize.py`). It keeps the effect's own light and shade, leaves the word's own ink alone, and
  keeps the colour at rest for decorated letterings.
- **What new painters need to do.** Nothing special, but keep the word's own ink as the word's colour, so a
  coloured entrance still lands on the plain word. `tests/test_effect_colors.py` covers this.

## Scenes

The poster scenes now have a jerk measure (`scene_score.py` reports `jerk`; aim for a p95 of about 1.3 or less).

| Scene | Jerk p95 |
|---|---|
| receding stack | 1.2 |
| word search | 1.2 |
| accordion fold | 1.3 |
| horizon rise | 1.6 |
| title grid | 1.2 (the last sung cell drains instead of switching off) |
| camera tour | 2.1 |
| word blink | 2.3 |
| proportion stack | 1.8 (colour and depth now ease as the sung row moves on) |
| stamp collage | 2.2 (stamps come down over two frames; older stamps fade to pale over 0.3 s) |
| type drum | 1.9 (the sung word cross-fades; letters fade as they turn away) |
| counter dive | 2.1 |
| halftone bloom | 1.8 |
| misregistration (new, judged 95 at s13) | 2.1 |
| block drop (new, judged 95 at s19) | 1.2 (polish left: centre and spread the second line change's pile; land the new block on its shoulder) |

The usual causes:

- **State that switches on the beat.** A size, colour, layout or plate changes in one frame when a new word starts.
- **Eases that begin before their word.** `t - since + 0.x`: the word appears part-way through.
- **Very short eases** of 0.1-0.2 s.

## Finishing a round

- **Goldens.** After a visual change, re-record them: `& $py tests/render_golden.py save`. The draft scene files
  must be out of `assets/scenes/` when you do (they are not in git).
- **Tests.** `& $py -m pytest tests -q`.
- **Push.** Commit as `jon castillo <jon.castillo.dev@gmail.com>`, then `git fetch`, `git rebase origin/main`,
  test again, and `git push origin HEAD:main`.
- **Records.** Note the round's grades in this file and in `LEDGER.md`.
