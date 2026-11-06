# Kinetic entrance scoring rubric

Built from the SVGator "50 kinetic typography examples" page, especially William Benjamin Powell's
"Don't Stop" (letters trade squat-heavy and tall-condensed proportions one at a time on a hard offset
extrusion with snappy in-out easing), his "LOL!" (letters spring up off a flat badge on deep extrusions,
fanned), "Snooze" (one letter multiplies into a shrinking chain and reels back), "Pride" (stacked colour
copies stepping per letter), and Hrvoje Grubisic's reel (repeat-word walls, page-peel reveals, sticker
badges, starburst windows, pill marquees, thin/heavy alternation, punchy riso palettes).

An effect is a word ENTRANCE in a lyric video: ~0.6 s (realtime flow) to 0.9 s, on any illustration
background, in any font, for words of 1 to 10+ letters. It must end exactly on the plain word.

## Overall score (pass: >= 95)

    overall = 0.40 * Impressiveness + 0.20 * Smoothness + 0.20 * Consistency + 0.20 * Uniqueness

Every part is 0-100. Reaching 95 needs Impressiveness >= ~90 together with near-perfect measured scores,
so a technically clean but ordinary effect cannot pass, and neither can a showy one that pops or spills.

## Impressiveness (0-100, judged by eye from contact sheets, per-frame strips and GIFs)

Five criteria, 0-20 each:

1. **Graphic craft** - bold, intentional design: confident shapes, colour that is punchy but harmonious,
   hard-edged print-like decoration (extrusions, badges, stickers, bursts) rather than blurry glows.
   Reference: Grubisic's palettes and stickers, Powell's extrusion.
2. **Choreography** - anticipation, overlap and follow-through; letters offset in time; at least two
   phases (e.g. arrive -> transform -> settle); easing with snap and spring, not linear drift.
   Reference: Powell's letter-by-letter relay.
3. **Letterform play** - the letters themselves transform (stretch, squash, multiply, extrude, slice,
   fold) rather than merely translating, scaling uniformly or fading.
4. **Legibility and payoff** - the word is clearly readable by ~85 % of the entrance, the motion
   serves the word, and the settle onto the plain word is a satisfying "lock".
5. **Lyric-video fitness** - looks good on dark and light backgrounds and with condensed, wide and
   lowercase fonts; does not look like cheap clip-art; would hold up when used on many words in a song.

Anchors: a plain fade = 20; a slide-in = 35; a competent After Effects per-letter scale-up preset with a
bounce = 70; a polished, layered title animation a studio would ship = 85-90; Powell's "Don't Stop" or
Grubisic's reel = 95-100.

## Smoothness (0-100, measured)

At 30 fps over the 0.6 s entrance on two words: the busiest frame step's share of all visible change
(pop; above 0.16 costs up to 70 points by 0.5) and on-off-on alpha flicker (above 0.25 costs up to 30).

## Consistency (0-100, measured)

On four words in four fonts (Anton caps, Dela Gothic lowercase, Big Shoulders mixed case, a lone "I"):
the last frame equals the plain word exactly (-30 otherwise); the 98.5 % frame is already nearly the word
(up to -25); the word is readable at 85 % (alpha correlation with the final word >= 0.93, else up to -10
per word); nothing spills further than ~1 word height around the word (up to -10 per word); renders
without error at intensity 0.4 and 1.8 (-15 per failure).

## Uniqueness (0-100, measured)

A motion-and-colour fingerprint (eight moments of the word's region, plus their differences) is compared
with every existing curated entrance effect and every other new kinetic effect. Score = 100 x (1 - highest
cosine similarity) / 0.30, capped at 100. For calibration, the most distinctive existing effects sit near
0.63-0.67 similarity (i.e. 100), the median existing effect near 0.9 (~33).

## Line-level scenes

Scenes (whole lyric lines, the poster camera) use the same five Impressiveness criteria. For legibility, judge
whether the sung word and the line are both readable as they are sung. Smoothness is measured per sung line by
`tools/scene_score.py`: the busiest frame step's share of that line's change, where above 0.12 costs up to 70
points by 0.5. Consistency and uniqueness are not yet measured for scenes, so their overall is an estimate that
takes 100 for both.

**Motion jerk.** `scene_score.py` also reports `jerk`: how abruptly the motion starts, stops and changes speed (the
frame-to-frame change in step size relative to the mean step; mean and 95th percentile). Smoothness only catches
single-frame pops, so a scene could score 100 and still feel jerky. Aim for a p95 jerk of about 1.3 or less. The usual
causes are state that switches on the beat (a size, colour, layout or plate that changes in one frame when a new word
starts), eases that begin before their word and so appear part-way through, eases shorter than about 0.25 s, and big
overshoots.

## Exits and the other effect families

`tools/score.py` scores any curated effect; set `PHASE=exit` for exits. An exit must start exactly on the plain word
(-30 otherwise), still read at 15 % of the way through (the same correlation test), and leave nothing behind (the
alpha left in the last frame, scored like the 98.5 % approach check). For the particle and material families (glass,
smoke, petals, ornament, material and the like), travel beyond the word is the effect itself, so spill is recorded but
not deducted. Kinetic type keeps the spill rule. Uniqueness compares against every other effect of the same phase.
