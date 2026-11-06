# Effects made by the lab

Overall = 0.4 × Impressiveness + 0.2 × (Smoothness + Consistency + Uniqueness); the pass mark is 95.

- **Impressiveness** is the latest independent-judge score. The judge was started fresh at round 29 and kept
  for every round since, so its calibration holds; these grades are from rounds 29-40.
- **Smoothness, consistency and uniqueness** are measured by `tools/` on the round-40 code.
- **Scenes:** only smoothness is measured (100 for every scene), so their overall takes 100 for consistency and
  uniqueness too.

All 29 pass. Several pass narrowly (95.0-95.1): a one-point drop in their judged grade would put them under
95 again.

## Word entrances (`kinetic` family)

| Effect (id) | Idea | Impr. | Smooth | Cons. | Uniq. | Overall |
|---|---|---|---|---|---|---|
| pop extrude (`kinetic-pop-extrude`) | Letters spring off a badge that lands tilted, on deep tapered extrusions whose depth surges along the word; the badge colour steps word to word | 93 | 100 | 100 | 100 | **97.2** ✅ |
| depth press (`kinetic-depth-press`) | Letters land raised on a long hard shadow, sink down-right over a hot band, hold, then rise flush with a flash of the accent that relays along the word | 90 | 100 | 100 | 100 | **96.0** ✅ |
| starburst (`kinetic-starburst`) | A comic burst grows its points behind letters that punch in, pulses out a rim-coloured ring, exits as a hollow rim and snaps in to an underline flash | 92 | 94.2 | 100 | 100 | **95.6** ✅ |
| echo trail (`kinetic-echo-trail`) | The word skids in tilted, trailing keylined copies in light, mid and dark steps that catch up letter by letter into a stepped depth | 90 | 97.5 | 100 | 100 | **95.5** ✅ |
| elastic stretch (`kinetic-elastic-stretch`) | Letters shoot tall (or squat-wide, alternating by word and letter pair), slam over a misregistered plate, and a late accent flash relays two letters at a time | 94 | 88.6 | 100 | 100 | **95.3** ✅ |
| bar wipe (`kinetic-scan-slice`) | Two colour bars carry the cap and lower halves in from opposite sides, flare wider, and hand the print over to the word's ink in a sweep | 90 | 96.5 | 100 | 100 | **95.3** ✅ |
| page peel (`kinetic-page-peel`) | A ghost-printed sticker slaps down and peels at an even pace; the letters under it spring up from small as the fold passes | 90 | 95.9 | 100 | 100 | **95.2** ✅ |
| inflate (`kinetic-inflate`) | Letters puff up as saturated balloons in two flat print tones, wobble, and switch to their own ink as they deflate | 90 | 95.5 | 100 | 100 | **95.1** ✅ |
| art window (`kinetic-art-window`) | Letters open onto the frame's painting, which pans and pushes in while the word grows; a thick accent line floods up and caps the letter tops | 88 | 99.5 | 100 | 100 | **95.1** ✅ |
| flip tiles (`kinetic-dot-stamp`) | Letters printed on tiles in two alternating shades flip over like a split-flap board to the plain letter | 88 | 99.4 | 100 | 100 | **95.1** ✅ |
| echo jump (`kinetic-echo-chain`) | The word builds, then a twin of one letter jumps up, leaving a totem of shrinking echoes in its own hue, and lands into its letter | 88 | 99.1 | 100 | 100 | **95.0** ✅ |
| echo cascade (`kinetic-echo-cascade`) | Each letter drops in on a fan of light, mid and dark copies in one hue that close down onto the baseline and retract into it | 89 | 97.1 | 100 | 100 | **95.0** ✅ |

## Glass and liquid chrome (`glass` family, `src/effects/particles/glass_fx.py`)

Rebuilt by Session B. Grades are from fresh judges (one for g3-g5, one for g6-g17, one from g18), harsher than the e1/x1 judge: the
first graded the untouched originals 51-70 against the same 93 anchor. Round g24. Glass sweep passes; the rest do not yet.

| Effect (id) | Idea | Impr. | Smooth | Cons. | Uniq. | Overall |
|---|---|---|---|---|---|---|
| glass sweep (`glass-sweep`) | Whole glass letters tumble ahead of a coloured pane that sweeps across and squashes each into place; a highlight then chases across and snaps each letter to its ink | 89 | 99.2 | 100 | 100 | **95.4** ✅ |
| glass mosaic (`glass-mosaic`) | A stream of tiles pours in on an arc (a different side per word) and turns over to set letter by letter; each letter pops as it sets and rocks as its neighbour lands | 78 | 91.3 | 100 | 100 | **89.5** |
| glass assemble (`glass-assemble`) | The word is spelled round a drawn glass hoop in small whole glass letters, a bright arc travelling round it; the letters peel off in order and grow into place, the hoop thins away, and the word squashes and stretches as it lands | 85 | 91.8 | 97.5 | 100 | **91.9** |
| glass prism (`glass-prism`) | Facets rise two letters at a time with a dispersion fringe pair (varied per word) that snaps together as each letter lands and flashes | 76 | 96 | 100 | 100 | **89.6** |
| glass spiral (`glass-spiral`) | A corkscrew: a thin glass spring screws in along the word's axis (from the left or the right by word), near side bright, far side dark, carrying the facets, and tightens onto each letter in turn | 74 | 100 | 100 | 100 | **89.6** |
| liquid chrome assembly (`liquid-chrome-assembly`) | Mercury rises out of a flat, strongly colour-cast pool below the word and climbs into it; the pool drains as the letters surface one by one, a sheen crosses, then it cools to ink | 73 | 92.1 | 100 | 100 | **87.6** |
| glass shatter (`glass-shatter`, exit) | A crack star opens on the first letter; each letter cracks on its own frame and blasts into several facets, the smallest fading first | 83 | 100 | 99.5 | 100 | **93.1** |
| glass impact (`glass-impact`, exit) | A glass ball strikes and carries on out to the right; letters are flung off one per two frames with a spin while the survivors jolt | 83 | 100 | 97.7 | 100 | **92.7** |
| glass fan (`glass-fan`, exit) | Whole letters fan open about a pivot below or above the word and flick off along the arc's tangent one by one | 76 | 96.5 | 100 | 100 | **89.7** |
| glass vortex (`glass-vortex`, exit) | The word turns as one to 70 degrees, then its facets shear onto one widening circle and trail off | 75 | 90.3 | 100 | 100 | **88.1** |
| glass cascade (`glass-cascade`, exit) | Frost sweeps down and across, then the facets pour away fanning from the middle, land on a floor, bounce and fade by letter | 78 | 99.2 | 100 | 100 | **91.0** |
| liquid chrome collapse (`liquid-chrome-collapse`, exit) | The word turns to colour-cast mirror and melts letter by letter into drips that pinch off and splash on a floor | 79 | 100 | 100 | 81.3 | **87.9** |

## Line-level scenes (`poster` camera)

| Scene (id) | Idea | Impr. | Smooth | Overall (est.) |
|---|---|---|---|---|
| word wall (`word-wall`) | A split-flap band of flat colour fields per word; marquee rows run while the sung word locks big in the middle | 93 | 100 | **97.2** ✅ |
| proportion stack (`proportion-stack`) | The line as a justified block; the sung row swells tall in colour while the rest squash, and the colour relays down the block | 92 | 100 | **96.8** ✅ |
| word spiral (`word-spiral`) | The line repeated along a spiral that fills the frame; ring copies of the sung word glow at half strength while it stamps full size in the eye | 91 | 100 | **96.4** ✅ |
| word seal (`word-seal`) | The line around a spinning badge (round, scalloped or sawtooth by line); the sung word is stamped big in the centre | 90 | 100 | **96.0** ✅ |
| receding stack (`receding-stack`) | The sung word slams in on a plate in front; earlier words step back into depth, sinking toward navy | 90 | 100 | **96.0** ✅ |
| word blink (`word-blink`) | One huge word per beat on its own flat band that slams in at varied heights and tilts, closing on a thin split line | 89 | 100 | **95.6** ✅ |
| type drum (`type-drum`) | The line wraps a turning drum whose letters foreshorten toward its edges; the middle row brings each sung word to the front | 89 | 100 | **95.6** ✅ |
| title grid (`title-grid`) | Words glide along the bold rules of a tilted grid that draws on; the sung word floods its cell with a squash | 88 | 100 | **95.2** ✅ |
| camera tour (`camera-tour`) | The camera flies word to word across a tight arrangement, each word with its own entrance; neighbours dim to cool navy | 88 | 100 | **95.2** ✅ |
| horizon rise (`horizon-rise`) | Sung words climb out of a horizon rule letter by letter, beside the two words before them, and sink back at the line's end | 88 | 100 | **95.2** ✅ |
| type ribbon (`type-ribbon`) | The line along a paper ribbon that ripples (a different course per line) and twists to show its tinted back; pinned flat and swollen where each sung word slides in on an accent block | 89 | 100 | **95.6** ✅ |
| accordion fold (`accordion-fold`) | The line on a pleated paper strip, one word per pleat; each sung pleat slaps flat to camera in the accent while the others stay folded and tinted | 89 | 100 | **95.6** ✅ |
| counter dive (`counter-dive`) | One huge word at a time; the camera pushes into a letter's counter (or a hole punched through the word) where the next word waits on a disc | 88 | 100 | **95.2** ✅ |
| word search (`word-search`) | The line hidden in a letter grid like a puzzle; a marker sweeps each sung word, which swells as the camera pushes in on it; found words keep a dark capsule | 89 | 100 | **95.6** ✅ |
| halftone bloom (`halftone-bloom`) | The line set big in a halftone dot screen (a different row layout per line); each sung word's dots swell into crisp solid type with a ripple through the screen | 89 | 100 | **95.6** ✅ |
| type mobile (`type-mobile`) | The line hangs on threads from a rail like a mobile; the sung word drops lower and big in the accent and swings toward the middle while its neighbours lift clear | 89 | 100 | **95.6** ✅ |
| stamp collage (`stamp-collage`) | Each sung word is rubber-stamped big with a squash and an ink-splatter ring; stamps build an inward-spiral collage laid out to overlap border to border | 88 | 100 | **95.2** ✅ |

## Lessons from rounds 30-40

- **Find which beat flickers before cutting.** Re-defining a painter with one beat removed at a time showed that
  one beat caused most of the flicker: elastic's late squash, and depth press's rebound shadow. Replacing a
  motion beat with a colour beat (an accent flash) keeps the second beat without the flicker, because the
  flicker metric reads alpha only.
- **Hard snaps cost smoothness.** Even eases on drops and peels (instead of expo snaps or sudden full-size
  appearances) raised echo cascade from 94.1 to 97.1, page peel from 89.2 to 95.9, and echo trail from 84 to 97.5.
- **Changes have to be big enough to see on a sheet.** About 8% growth, a 3% darker tone, a 2 px band or a
  short breath were each reported as "no visible change". Check the sheet before asking for a grade.
- **Never fade a whole shared layer.** It can hold other words; draw on a layer of your own and composite it.
