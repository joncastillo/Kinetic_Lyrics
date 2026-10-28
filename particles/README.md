# Typography particle recipes

Studio exposes 34 entrances and 19 exits from the curated catalog.
Additional legacy recipes remain on disk for compatibility.
Every recipe operates on fragments of the actual word.

Studio lets you pick one preset per phase or use **Mixed**. **Browse entrances**
and **Browse exits** open a large effect browser: the list scrolls independently
beside its preview (below the pinned preview on mobile). Search, family filters
and Selected only help manage the list. Click a preset to preview without changing
the selected effect; **Use this effect** applies it. Checkboxes choose the mixed
set and select mixed mode automatically. All/Clear change the entire set. Empty
means clean type for that phase. Profiles, jobs and rebuilds retain the choices.

Every preview uses the exact recipe and current intensity/speed. Dust uses fine
grains, snow uses branched crystals, smoke uses soft puffs, bubbles use rings,
sparks use hot streaks, petals use leaf silhouettes, and pixels use stepped blocks.
These materials also appear in exported videos. The intact reading hold is
preserved before a glyph turns into its selected material. Glass retains the
actual fractured glyph surface and individual tumbling.

To add an effect, copy a JSON file into the appropriate phase folder and give it a
unique lowercase, hyphenated filename. Its filename without `.json` is the saved
effect ID. Edit its display name and motion settings. No Python import, registry,
front-end list, or build step is required. Removing the file removes that choice.
Refresh Studio to reload its choices. New render jobs rescan the folders; an
already-running render keeps its effect snapshot so exports remain consistent.
Saved projects whose recipe has been removed use clean typography with a warning.
Invalid recipes are skipped with a warning rather than breaking the Studio.

Example `exit/glass-shatter.json`:

```json
{
  "name": "Glass shatter",
  "family": "glass",
  "trajectory": "radial",
  "spread": 1.65,
  "gravity": 0.85,
  "spin": 1.25,
  "twist": 0,
  "stagger": 0.1,
  "density": 1
}
```

Families: glass, dust, sparks, ribbons, pixels, petals, snow, smoke, bubbles, ink,
vortex, magnetic, letters, ornament, trees, flock, cinematic. Trajectories:
radial, left, right, up, down, spiral, wave, fan, grow.
`spread` controls travel distance, `gravity` downward acceleration (negative rises),
`spin` angular motion, `twist` spiral motion, `stagger` variation in fragment release,
and `density` fragment count. The loader validates finite numbers and safe ranges;
see `particle_catalog.py` for the exact bounds. Existing engines can be combined
and tuned through these recipes; a new material or simulation requires extending
the shared runtime in `particle_motion.py`.

Glass exits spread cracks, pause until 25% of the exit interval, and then eject
irregular Voronoi fragments with individual three-axis rotation, perspective size
variation, gravity and changing face/edge highlights. Glass entrances are separate
assembly recipes. This is a deterministic raster projection of rotating shards,
not a refractive ray-traced glass simulation.

Words begin entrance animation at their unchanged alignment timestamps. Upcoming
words have an 8% opacity preview, independent of activation. Exits start after the
individual word ends plus a one-second reading hold. Exits take precedence over the next line's advance preview;
tightly adjacent lines may still have insufficient room for a full exit.
Intensity zero disables fragment effects. Motion speed changes animation duration
without moving the sung cues. Geometry is cached only for the current lyric line;
rendering the same timestamp gives the same frame even after seeking.

CLI:

```powershell
python kinetic_lyrics.py song.wav lyrics.txt --entrance-effect dust-coalesce --exit-effect glass-shatter
```

`--type-effect` and older Studio profiles retain their legacy pairings. In
particular, legacy `shatter` now selects a clean entrance and a glass-shatter exit.
Independent entrance/exit selections override those pairings.

For CLI mixed mode, `--entrance-pool` and `--exit-pool` accept JSON lists of IDs.
An omitted pool enables all available recipes; `[]` enables none.

## Formation and breakup choreography

Generic material entrances use interpolated signed-distance contours to reshape
particles into the actual glyph patches, rather than crossfading in a whole word.
Material color and shape remain visible during travel. Glass, letters and the
formation presets have their own assembly paths.

`petals-wind-lettering`, `petals-breeze-lettering` and
`petals-spiral-lettering` set `hold: "particles"`: many individual petals follow
curling, staggered paths to destinations sampled from the glyph mask. They remain
petals at rest. Exits operate on that petal-shaped word rather than switching to
solid lettering. This hold mode also supports growth trajectories in other material families.

`letters-spin-*` uses individual glyph strips with independent three-axis
rotation and directional approaches. Glass exits have three stages: crack/hold,
ejection of larger pieces, then a second fracture into smaller, faster-spinning
pieces. Children inherit the parent pose and trajectory before their new impulse.
Dust, sparks, ribbons, pixels, petals, snow, smoke, bubbles, ink, vortex and
magnetic particles have material-specific drift, drag, flutter, growth and
terminal behavior. Exit tails can continue behind the next line instead of being
compressed into a short inter-line gap.


## Effect descriptions and AI selection

`descriptions.json` maps phase and effect ID to a short visual/mood description,
with at most ten whitespace-separated words. Keep every recipe described. The
shared metadata file lets older running workers continue reading their recipes.
New loaders also accept an inline `description`; it takes precedence. Descriptions
are returned in the catalog API and appear in Studio's searchable effect browser.

AI typography receives only checked effects, each with its ID, name and short
description. Each line also receives its matching existing illustration description,
artwork mode and scene palette/style/energy. No extra vision inference is needed.
When no illustration description exists, selection uses lyrics and scene context.
Descriptions and background context participate in the direction cache signature.
Changing either causes direction to be planned again when AI mode is selected.

The cinematic family adds paired prismatic, aurora silk, liquid chrome and ember
entrances/exits. They reuse actual glyph fragments, deterministic depth projections,
shaded streamers, droplets and analytic trails. Entrances start invisible and fade
in; intact holds preserve the original glyph pixels and holes. Departure paths are
independent of arrival paths. Existing per-word timing and speed controls apply.
CPU previews use the same renderer and do not load any image or text model.
