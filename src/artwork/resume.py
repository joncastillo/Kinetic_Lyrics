"""Reuse completed artwork when a studio job resumes at review or rendering."""
import json
from pathlib import Path


def completed_artwork(data,folder,args):
    folder=Path(folder)
    config_path=folder.parent/'config.json'
    if not config_path.is_file():return None
    config=json.loads(config_path.read_text(encoding='utf-8'))
    if config.get('start_step') not in ('review','render'):return None
    if not getattr(args,'audio',None) or Path(config.get('audio','')).resolve()!=Path(args.audio).resolve():return None
    from artwork.active import select_manifest
    manifest=select_manifest(folder.parent,config)
    job=json.loads(manifest.read_text(encoding='utf-8'))
    paths=[manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError('Some artwork is missing. Resume from Images to finish generation before review.')
    mode=job.get('artwork_mode','cutout')
    if getattr(args,'artwork_mode','cutout')!=mode:
        raise ValueError('Changing artwork layout needs new artwork. Keep the saved layout to resume Review, or restart from Prompts.')
    groups=job.get('groups',[])
    if job.get('line_groups') is not None:
        from direction.song_structure import valid_line_groups
        indices=job['line_groups']
        if not valid_line_groups(indices,len(data)) or [' / '.join(data[i]['text'] for i in group) for group in indices]!=groups:
            raise ValueError('Saved section-aware artwork does not match the lyric lines')
        line_count=max(map(len,indices))
    else:
        line_count=next((n for n in range(1,len(data)+1)
            if [' / '.join(line['text'] for line in data[i:i+n]) for i in range(0,len(data),n)]==groups),None)
    if line_count is None:raise ValueError('Saved artwork does not match these lyric lines. Resume from Prompts for changed lyrics.')
    args.image_seed=job['seed'];args.illustration_lines=line_count
    print(f'Resuming {config["start_step"]}: reusing all {len(paths)} saved images; image generation is skipped.',flush=True)
    return paths
