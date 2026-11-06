# Studio front end

`studio.html` is markup only. Behaviour and styling live in small modules, served flat from this
folder by `studio/server.py` (any `studio-*.css` or `studio-*.js`; pictures in `art/` as `/studio-art/<name>.webp`).

The pipeline graph's stage version selectors and whole-pipeline history selector
are in `studio-models.js`. They read `pipeline_history` from the job snapshot and
post selections to `/api/jobs/<id>/pipeline-version`. Controls are disabled while
work is running or queued. A stage with no compatible saved output shows
"Needs regeneration"; the Pipeline selector restores an exact saved combination.

## Styles (load order matters)

| File | Holds |
|---|---|
| `studio-tokens.css` | Design tokens for the Night (dark) and Day (light) themes and the mesh backdrop. Change colours here only. |
| `studio-base.css` | Reset, type scale, inputs, buttons, badges, info buttons and popovers. |
| `studio-header.css` | Top bar, production deck (GPU map and model list on the left, session, profile and run controls on the right), pipeline stage rail, video-tools dock. |
| `studio-layout.css` | Page grid, workspace tabs, the settings drawer, panels, breakpoints. |
| `studio-inspector.css` | The settings sidebar: sections, fields, GPU monitor, typography controls, sticky footer. |
| `studio-workspace.css` | Home screen, session card, review banner, artwork gallery, typography pictures, video, timeline tab, log. |
| `studio-dialogs.css` | Modals, toast, effect browser, stem timeline, framing, storyline. |

## Scripts (classic scripts sharing one global scope, in load order)

| File | Holds |
|---|---|
| `studio-boot.js` | Loaded in the head: restores the theme, backdrop and panel colour from the active profile before the first paint. |
| `studio-models.js` | Model catalogue, GPU-fit, the header's GPU map, stage rail, downloads and reference-regeneration dialogs. |
| `studio-scenes.js` | Scene cards, entry/exit descriptions, tag and text filters, and individual configuration panels. Overrides live in `kinetic.scene_settings`; reset affects only one scene. |
| `studio-fx-sim.js` | Canvas previews for the will-o'-wisp and beat effects. |
| `studio-story.js` | Storyline dialog. |
| `studio-particles.js` | Effect browser, previews, the changes-since-render panel (video tools), video history, sidebar label captions. |
| `studio-app.js` | API access, session picker, lyric/audio inputs, uploads, Generate button state. |
| `studio-gallery.js` | Production log, illustration cards, inspect and replace-or-verify dialogs, typography pictures. |
| `studio-session.js` | Render-setting restore, job polling, applying updates, start-up. |
| `studio-profiles.js` | Saved profiles and the header's profile picker, model pickers, speech models. |
| `studio-shell.js` | Workspace tabs, the settings drawer with Models and Files and Appearance tabs, settings search, collapsible sections, theme switch. The run option and start button live in the header, Redo in new session in the Project panel. |
| `studio-appearance.js` | Settings > Appearance: current Day and Night backdrop previews open a gallery. Backdrops and panel colours are kept in the profile's `appearance` field. |
| `studio-home.js` | Home screen: grid of finished projects and the project list with badges, from the job list. |
| `studio-project-tabs.js` | Project panel sub-tabs (Song, Story, References, Artwork, Typography, Scenes, Word effects, Kinetic); the preset box stays beside them. |
| `studio-projects.js` | Rename and delete projects (confirmation dialog), default project names. |
| `studio-tips.js` | Folds long help text behind info buttons and popovers. |
| `studio-timeline.js` | Stem timeline (inline under the Timeline tab) and the clip framing dialog. |


Backdrops live in `art/`, named for their theme (`day-meadow.webp`, `night-osaka-lanterns.webp`, `night-moonlit-meadow.webp`). `studio-boot.js` names each theme's default. Settings > Appearance also accepts user pictures, kept under the studio output folder in `backdrops/`. The glass above them is translucent and never blurs them. Element ids and `name` attributes in `studio.html` are the contract between modules: keep them when
restructuring markup. The settings form is one DOM: the drawer's step bar only filters which sections show.
