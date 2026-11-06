"""Render the realtime flow's will-o'-wisp through the end of its run, to MP4 + contact sheet.
usage: python wisp_demo.py OUTDIR [font_family]"""
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'src'))
from core.paths import PROJECT_ROOT  # noqa: E402
from effects.particles.preview import scene_backdrop  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
family = sys.argv[2] if len(sys.argv) > 2 else 'auto'
from render.compositor import Compositor  # noqa: E402
from direction.typography import rules_plan  # noqa: E402
from direction.theme import theme_for  # noqa: E402
LINES = ((.5, 'golden light upon the water'), (3.2, 'hold me close until the morning'))
SIZE, SECONDS, FPS = (960, 540), 8.5, 24
data = []
for start, text in LINES:
    words = [dict(text=w, start=round(start+i*.4, 3), end=round(start+i*.4+.36, 3)) for i, w in enumerate(text.split())]
    data.append(dict(text=text, words=words, section_id=0, section_label='Verse'))
plan = rules_plan(data, theme_for('bright'))
art = scene_backdrop(PROJECT_ROOT/'.preview-cache', SIZE)
c = Compositor(data, plan, SIZE[0], SIZE[1], SECONDS, illustrations=[str(art)], illustration_lines=len(data),
               artwork_mode='fullscreen', reading_flow='realtime', entrance_effect='mixed', exit_effect='mixed',
               font_family=family, kinetic=dict(fade=False, camera='still'))
frames = [c.frame(n/FPS) for n in range(round(SECONDS*FPS))]
name = f'wisp-finale{"-"+family if family != "auto" else ""}'
proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{SIZE[0]}x{SIZE[1]}',
                         '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18',
                         str(out/f'{name}.mp4')], stdin=subprocess.PIPE)
for f in frames:
    proc.stdin.write(f.convert('RGB').tobytes())
proc.stdin.close(); proc.wait()
end = c.realtime.thread_path()['keys'][0][-1] if hasattr(c.realtime, 'thread_path') else 6.
picks = [frames[min(len(frames)-1, max(0, round((end+d)*FPS)))] for d in (-.4, -.1, .05, .15, .3, .5, .8, 1.2)]
sheet = Image.new('RGB', (480*4, 270*2))
for i, f in enumerate(picks):
    sheet.paste(f.convert('RGB').resize((480, 270)), ((i % 4)*480, (i//4)*270))
sheet.save(out/f'{name}.png')
print('wisp end at', round(end, 2))
