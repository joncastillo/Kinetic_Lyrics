"""Archive exact judge images/data and compact review videos into the repository.

Original GIFs and generated backdrop caches can be retained separately with --raw-copy.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'tmp/scene-effects-lab')
    parser.add_argument('--raw-copy', type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    destination = ROOT / 'automation/scene-effects-lab/evidence'
    if args.raw_copy:
        raw = args.raw_copy.resolve()
        if raw == source or raw.is_relative_to(source):
            parser.error('Raw archive must be outside the source folder')
        shutil.copytree(source, raw, dirs_exist_ok=True)
        print('Original evidence copied to ' + str(raw), flush=True)
    videos = []
    copied = 0
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path.name.startswith('scene-backdrop-'):
            continue
        relative = path.relative_to(source)
        if path.suffix == '.gif':
            target = (destination / relative).with_suffix('.mp4')
            target.parent.mkdir(parents=True, exist_ok=True)
            videos.append((path, target))
        elif path.suffix in ('.png', '.json', '.md', '.zip'):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1

    def encode(pair):
        path, target = pair
        if target.is_file():
            return
        subprocess.run(
            [
                'ffmpeg',
                '-hide_banner',
                '-loglevel',
                'error',
                '-y',
                '-i',
                str(path),
                '-an',
                '-c:v',
                'libx264',
                '-threads',
                '2',
                '-preset',
                'fast',
                '-crf',
                '14',
                '-pix_fmt',
                'yuv420p',
                '-movflags',
                '+faststart',
                str(target),
            ],
            check=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(encode, videos))
    for path in (ROOT / 'automation/scene-effects-lab/reviews').glob('*.json'):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        archived = destination / path.stem
        if not archived.exists():
            continue
        manifest.setdefault(
            'original_evidence_folder', manifest.get('evidence_folder', 'tmp/scene-effects-lab/' + path.stem)
        )
        manifest['evidence_folder'] = archived.relative_to(ROOT).as_posix()
        manifest['review_video'] = 'animation.mp4'
        path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        if (archived / 'scores.json').exists():
            (archived / 'scores.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    total = sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())
    print(f'Archived {copied} data/image files and {len(videos)} review videos ({total/1024**2:.1f} MiB).')


if __name__ == '__main__':
    main()
