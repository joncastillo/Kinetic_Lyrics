"""Select and persist the current illustration run while retaining older caches."""
import json
from pathlib import Path


def _read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def select_manifest(folder,config=None,state=None):
    folder=Path(folder);base=(folder/'video.artwork').resolve()
    config=_read(folder/'config.json') if config is None else config
    paths=[p for p in (folder/'video.artwork').glob('*/illustrations.json')
           if not p.is_symlink() and p.resolve().is_relative_to(base)]
    if not paths:raise ValueError('Illustration subjects are not ready yet')
    resume=config.get('start_step') in ('review','render')
    def matches(path):
        data=_read(path)
        return all(key not in config or key not in data or data[key]==config[key]
                   for key in ('seed','model','artwork_mode')) and (
                   'image_seed' not in config or data.get('seed')==config['image_seed']) and (
                   'image_model' not in config or data.get('model')==config['image_model'])
    recorded=(state or {}).get('active_manifest') or _read(folder/'active-artwork.json').get('manifest')
    if recorded:
        candidate=Path(recorded)
        if not candidate.is_absolute():candidate=folder/candidate
        if candidate in paths and (resume or matches(candidate)):return candidate
    matching=[p for p in paths if matches(p)]
    if matching:return max(matching,key=lambda p:p.stat().st_mtime_ns)
    if len(paths)==1 or resume or 'image_seed' not in config:
        return max(paths,key=lambda p:p.stat().st_mtime_ns)
    raise ValueError('Waiting for the current illustration manifest')


def record_manifest(manifest):
    manifest=Path(manifest).resolve()
    if manifest.name!='illustrations.json' or manifest.parent.parent.name!='video.artwork':return None
    folder=manifest.parent.parent.parent
    if not manifest.is_file() or not manifest.is_relative_to((folder/'video.artwork').resolve()):return None
    from artwork.gallery import publish_gallery
    publish_gallery(manifest)
    relative=manifest.relative_to(folder).as_posix();target=folder/'active-artwork.json'
    if _read(target).get('manifest')==relative:return relative
    temporary=target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(dict(manifest=relative)),encoding='utf-8');temporary.replace(target)
    return relative
