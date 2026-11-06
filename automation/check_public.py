"""Reject private implementation paths anywhere in the reachable public history."""
import subprocess
from pathlib import PurePosixPath


def private_path(name):
    path = PurePosixPath(name)
    return (
        path.name.lower() in ('agents.md', 'claude.md', '.private-repository')
        or name.startswith(('src/models/online/', 'src/video_generation/', 'src/scene_text/', '.claude/'))
        or name in ('assets/kinetic_lyrics_ui.png', 'src/clip_effects.py', 'src/direction/cinemagraph.py',
                    'src/direction/motion.py', 'src/frontend/studio-shadow-demo.js',
                    'src/frontend/studio-scene.js', 'src/render/layered_scene.py')
        or name.startswith(('src/frontend/art/scene-assets/', 'src/frontend/art/day-meadow-marquee'))
    )


def main():
    tracked = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
    history = subprocess.check_output(['git', 'log', '--all', '--format=', '--name-only']).decode().splitlines()
    forbidden = sorted({name for name in tracked + history if name and private_path(name)})
    if forbidden:
        raise SystemExit('Private paths found:\n' + '\n'.join(forbidden))
    print('Public working tree and all reachable history contain no private implementation paths.')


if __name__ == '__main__':
    main()
