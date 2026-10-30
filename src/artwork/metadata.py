"""Keep the exact prompt with each candidate and archived selection."""
import json
from pathlib import Path


FIELDS={'prompt':'prompts','subject':'visual_descriptions','layout':'layouts','reference_mode':'reference_modes'}


def variant_metadata(path,job,index):
    path=Path(path)
    metadata={key:job[field][index] for key,field in FIELDS.items() if field in job}
    metadata.setdefault('subject',metadata.get('prompt',''))
    sidecar=path.with_suffix('.artwork.json')
    try:
        if sidecar.exists():return {**metadata,**json.loads(sidecar.read_text(encoding='utf-8'))}
        selection=path.with_suffix('.selection.json')
        if selection.exists():
            source=Path(json.loads(selection.read_text(encoding='utf-8')).get('selected',''))
            if source.is_file() and len(source.parents)>3 and source.parents[2].name=='candidates' and source.parents[3]==path.parents[2]:
                return variant_metadata(source,job,index)
        manifest=path.parent/'illustrations.json'
        if manifest.exists():
            source=json.loads(manifest.read_text(encoding='utf-8'));position=0 if len(source['prompts'])==1 else index
            metadata.update({key:source[field][position] for key,field in FIELDS.items() if field in source})
    except (OSError,ValueError,IndexError,KeyError):pass
    return metadata


def select_metadata(manifest,index,metadata):
    manifest=Path(manifest);job=json.loads(manifest.read_text(encoding='utf-8'))
    for key,field in FIELDS.items():
        if key not in metadata:continue
        if field not in job:
            if field=='visual_descriptions':job[field]=list(job['prompts'])
            else:continue
        job[field][index]=metadata[key]
    temporary=manifest.with_suffix('.tmp.json');temporary.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(manifest)
