"""Render line-level scenes through the real Compositor/scene mix and score them.

usage: python scene_score.py OUTDIR scene-id [...]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'src'))
from core.paths import PROJECT_ROOT  # noqa: E402
from effects.particles.preview import scene_backdrop  # noqa: E402

LINES = ((.5, 'golden light upon the water'), (3.4, 'hold me close until the morning'), (6.6, "don't stop now"))
SIZE, SECONDS, FPS = (960, 540), 9.0, 24


def render(scene_id):
    from render.compositor import Compositor
    from direction.typography import rules_plan
    from direction.theme import theme_for
    data = []
    for start, text in LINES:
        words = [dict(text=w, start=round(start+i*.38, 3), end=round(start+i*.38+.34, 3)) for i, w in enumerate(text.split())]
        data.append(dict(text=text, words=words, section_id=0, section_label='Verse'))
    plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=len(data), scene=scene_id)])
    art = scene_backdrop(PROJECT_ROOT/'.preview-cache', SIZE)
    c = Compositor(data, plan, SIZE[0], SIZE[1], SECONDS, illustrations=[str(art)], illustration_lines=len(data),
                   artwork_mode='fullscreen', reading_flow='mixed', entrance_effect='mixed', exit_effect='mixed',
                   kinetic=dict(scenes=[scene_id], fade=False))
    return [c.frame(n/FPS) for n in range(round(SECONDS*FPS))]


def smoothness(frames):
    data = [np.asarray(f.convert('RGB'), np.float32)/255 for f in frames]
    steps = np.array([np.abs(b-a).mean() for a, b in zip(data, data[1:])])
    # Per line: the busiest single step's share of that line's change (line changes are separate events).
    events = np.array_split(steps, len(LINES))
    pops = [float(e.max()/(e.sum()+1e-9)) for e in events]
    score = 100-sum(max(0., pop-.12)/(.5-.12)*70/len(pops) for pop in pops)
    return dict(pops=[round(p, 3) for p in pops], score=round(max(0., score), 1))


def jerk(frames):
    """How abruptly the motion starts, stops and changes speed: the frame-to-frame change in the size of each frame
    step, relative to the mean step (grey, half size). Lower is calmer. Single-frame pops are smoothness's job; this
    catches snappy eases, sudden resets and overshoots that read as jerky over several frames."""
    grey = [np.asarray(f.convert('L').resize((SIZE[0] // 2, SIZE[1] // 2)), np.float32) / 255 for f in frames]
    steps = np.array([np.abs(b - a).mean() for a, b in zip(grey, grey[1:])])
    change = np.abs(np.diff(steps)) / (steps.mean() + 1e-9)
    return dict(mean=round(float(change.mean()), 3), p95=round(float(np.percentile(change, 95)), 3))


def main():
    out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
    results = {}
    for scene in sys.argv[2:]:
        frames = render(scene)
        proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
                                 f'{SIZE[0]}x{SIZE[1]}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt',
                                 'yuv420p', '-crf', '18', str(out/f'scene-{scene}.mp4')], stdin=subprocess.PIPE)
        for f in frames:
            proc.stdin.write(f.convert('RGB').tobytes())
        proc.stdin.close(); proc.wait()
        picks = [frames[min(len(frames)-1, round(t*FPS))] for t in (.3, .6, .9, 1.4, 2.0, 2.8, 3.3, 3.7, 4.5, 5.6, 6.5, 7.2)]
        sheet = Image.new('RGB', (480*4, 270*3))
        for i, f in enumerate(picks):
            sheet.paste(f.convert('RGB').resize((480, 270)), ((i % 4)*480, (i//4)*270))
        sheet.save(out/f'scene-{scene}.png')
        results[scene] = dict(smoothness=smoothness(frames), jerk=jerk(frames))
        print(scene, results[scene], flush=True)
    path = out/'scene-metrics.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    previous.update(results)
    path.write_text(json.dumps(previous, indent=1))
    show = out.parent/'showcase'
    show.mkdir(exist_ok=True)
    import shutil
    for scene in sys.argv[2:]:
        shutil.copy2(out/f'scene-{scene}.mp4', show/f'scene-{scene}.mp4')


if __name__ == '__main__':
    main()
