# Scene effects lab

This lab evaluates rendered scene typography, separately from the particle entrance lab.
The fixed rubric weights spectacle 40%, readability 20%, choreography 20%, craft 15%
and originality 5%. The requested pass threshold is 95/100. Successful rendering and
functional tests do not count as artistic approval.

Run from the repository root with the project's Python environment and Ollama running:

```powershell
python automation/scene-effects-lab/score.py --round r01 --scenes quiet-focus plain-blocks
```

Omit `--scenes` for the entire catalogue. `--model` selects an installed vision model;
the default is `qwen3.8:27b`. `--render-only` creates evidence without inventing scores.
`--extra-packages` optionally points at an isolated test dependency directory.

Every round is kept under `tmp/scene-effects-lab/<round>/` with an animated GIF,
timestamped contact sheet, large settled frame, portrait and light-background samples,
raw judge response, measured frame differences and computed weighted score. The
manifest records the model, rubric hash, source hash, weights and pass threshold.
Existing rounds cannot be overwritten. Use a new round name after revising a renderer.

Review the judge's visible evidence before editing: a vision model can mistake a
deliberate transition for a defect. Frame-difference metrics describe changes, not
professional polish. Never insert assumed 100s, lower the threshold or resample
unchanged artwork just to obtain a passing answer. Keep failed revisions in the record.

The scene browser groups presets into families for editing. Preset IDs stay stable,
so a visual revision must be evaluated against that preset's earlier rounds.
