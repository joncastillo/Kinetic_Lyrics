# Paused checkpoint — 2026-11-07

**Paused at the user's request. Do not automatically resume experiments. The 95/100 artistic-quality target is NOT met.**

## Implemented

- Scene previews disable inherited confetti, beat lights, blur and background shake.
- Ten original studio backgrounds: five dark, five light. Each preset starts with a randomized dark background; arrows cycle all ten. Choices are session-local and do not change the actual video.
- Color panel with native picker, swatches, hex entry and Automatic reset.
- Live, debounced slider updates, loading/error status, retry, larger preview when configuring a preset, and 24 fps GIFs with a shared palette.
- 32 stable scene IDs grouped into nine families. Editorial, Gallery caption and Baseline reveal share layout/placement/phrase controls; saved IDs remain compatible.
- Per-scene typefaces, including cache isolation and inheritance of an explicit global font choice.
- `quiet-focus` is now displayed as **Optical focus**: outline initial, optical-band reveal, parallax and reflection. A lower-scoring dimming/drift change was reverted to the stronger R07 implementation.
- Clean **3D blocks** no longer inherits arbitrary particle effects or keyword icons. It has per-line composition, adaptive ink, actual extruded contour sidewalls, depth testing, directional lighting, metallic faces and letter cascades. Other decorated stage presets retain their effects.
- Dedicated scoring lab, fixed rubric, strict grading, GPU lease support, immutable round names, source snapshots, raw judge outputs, review archives and a score ledger.

## Scores and limits

Weights: spectacle **40%**, readability **20%**, choreography **20%**, craft **15%**, originality **5%**. Pass: **95/100**, with no critical defects. Missing/truncated responses are unscored, never passes.

- **0 of 32 presets has a recorded pass.**
- Best recorded Optical focus result: **88.2**, `candidate-serif` (font `serif`, size `1.2`, motion `1.35`). This is a historical candidate configuration, not proof that the current default scores 88.2.
- Best recorded 3D blocks result: **87.55** across several rounds, including `mesh-default`.
- `catalogue-r01` contains the initial pass for the other 30 presets; highest was Word spiral, **78.05**. Those used the earlier contact-sheet evidence protocol and have not all been rerun with the improved sequence protocol.
- Qwen sometimes misidentified upcoming words as clipping or dark-on-light text as white-on-white. Inspect evidence rather than blindly following its critique. Gemma cross-checks of R08 scored both priority scenes **79.75**. Qwen-VL cross-checking truncated and produced no valid score.
- `candidate-serif-refined` was stopped during wrap-up: Optical focus's response truncated; 3D blocks has rendered evidence but **no completed score**. Its manifest explicitly records the pause.
- Unanswered preference question: should 95 apply to each family's flagship or every variant, including deliberately quiet captions? Do not assume approval to lower the target, delete weak presets, or count only flagships.

## Saved artifacts

- `reviews/*.json`: durable scores, critique, settings and provenance.
- `ledger.json`: best recorded scores/configurations, not blanket approval of current code.
- `evidence/<round>/`: exact PNG judge inputs, raw JSON, frame labels, rubric, available source snapshots and compact H.264 review videos (`animation.mp4`). These are committed.
- Original GIFs and all temporary evidence were copied to **`D:\dev\projects\kinetic_lyrics\tmp\scene-effects-lab-20261107-wrapup`**. The committed MP4s are review copies; original GIFs remain in this local archive.
- R07 and later rounds have `source.zip`; earlier rounds have renders/source hashes but no complete source snapshot.
- `calibrate.py` currently expects R08 inputs under `tmp/scene-effects-lab/r08/plain-blocks`. Restore them from the archive before running it, or update its input-path handling. Its initial version overwrote the latest calibration file on another run; the retained latest calibration is Gemma's successful factual check. Do not infer missing calibration results.

## Validation and runtime state

- Last broad CPU/DOM checkpoint: **97 tests passed, 3 skipped**, plus DOM checks for filtering, selections, color validation, font/control persistence, background arrows and live preview requests.
- Additional contour tests: **2 passed** with scikit-image available. Additional preview tests passed after the 24 fps/shared-palette update.
- Actual HTTP tests on isolated port 8766 returned 32 scenes, 10 backgrounds and nine families; Baseline reveal produced distinct GIF hashes for changed fonts/settings/backgrounds.
- Real GPU renders/judge runs exercised the new sidewall renderer, including `mesh-default` and `candidate-geometric`. The latest tree has not had a fresh exhaustive render/control sweep after every subsequent edit.
- No native-browser visual QA was completed; the browser automation host/policy was unavailable. DOM and HTTP tests are not a substitute for that review.
- Temporary Studio **8766 was stopped**, the active scorer was terminated, and judge models were released. This task did not restart public Studio 8765. Check its state before launching it.
- Another task shares the RTX 4090 and uses **`D:\dev\projects\kinetic_lyrics_pro\.image-generation.lock`**. Honor that OS file lock; its mere existence does not mean it is held. The scorer unloads its model before releasing the lease.

## Resume, only when requested

1. Read this handoff, `RUBRIC.md`, `ledger.json` and the relevant raw reviews. Inspect the linked held frames and animations. Do not label a successful render as artistic approval.
2. Use the main checkout's Python environment. Requirements already include ModernGL and scikit-image. This worktree also used temporary packages in `tmp/scene-deps`; do not assume those exist in a new checkout.
3. Regenerate the local ledger view with `python automation/scene-effects-lab/report.py`.
4. Use a **new** round name; old rounds deliberately cannot be overwritten:

```powershell
.venv\Scripts\python.exe automation\scene-effects-lab\score.py --round resume-r01 --scenes quiet-focus plain-blocks --gpu-lock D:\dev\projects\kinetic_lyrics_pro\.image-generation.lock
```

`--settings automation/scene-effects-lab/evidence/candidates/serif.json` evaluates the saved serif configuration. `--render-only` produces evidence without a judge. `--model` selects an installed vision model. Diagnose truncated output as an unscored failure; do not reroll valid low scores to hunt a pass.

5. Finish/review the priority designs and then rerun the remaining catalogue with the same fixed weights and threshold. Verify any claimed passing preset on additional lyric lengths and both orientations. No candidate settings have been silently promoted to approved defaults.
6. Relevant checks:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_scene_judge.py tests/test_scene_previews.py tests/test_scene_sculpture.py tests/test_scene_controls.py tests/test_stage.py tests/test_cinema.py tests/test_kinetic_type.py
.venv\Scripts\python.exe -m ruff check src tests automation/scene-effects-lab
```

The DOM test requires jsdom: `node tests/scene_controls_dom.cjs <jsdom-module-path> <catalogue-json> <backgrounds-json>`. Generate those JSON files from `scene_catalog().values()` and `backdrop_choices()`.

7. Archive new evidence with `archive.py`, regenerate the ledger, and update this handoff. Keep failures and model/protocol differences visible. Do not resume the 95-point iteration automatically after this parked checkpoint.
