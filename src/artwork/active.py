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
    resume=config.get('start_step') in ('review','render') or bool(
        (state or {}).get('active_manifest') and (state or {}).get('status') in ('running','queued'))
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
    from core.files import write_text_atomic
    write_text_atomic(target,json.dumps(dict(manifest=relative)))
    return relative


def archive_images(folder,config):
    """Move the active run's images and replacement candidates aside so a restart at Images regenerates every one.

    Nothing is deleted: the files land in a dated previous-* folder next to them. Returns the manifest kept for its
    prompts, or None when there is no saved run to restart."""
    folder=Path(folder)
    try:manifest=select_manifest(folder,dict(config,start_step='review'))
    except ValueError:return None
    archive_folder(manifest.parent)
    return manifest


def archive_folder(artwork, references=False, story=False):
    """Move one run's images, and the job's replacement candidates, into a dated previous-* folder beside them.
    Keep prompts and checkpoints. Earlier-stage restarts also archive sheets, story and saved selections."""
    import shutil,time
    artwork=Path(artwork);folder=artwork.parent.parent
    archive=artwork/(time.strftime('previous-%Y%m%d-%H%M%S')+f'-{time.time_ns()%1000000000:09d}')
    root=folder.resolve()
    if artwork.is_symlink() or not artwork.resolve().is_relative_to(root) or not archive.resolve().is_relative_to(root):
        raise ValueError('Artwork archive path leaves the project.')
    for path in list(artwork.iterdir()):
        # the storyline belongs to the prompts, which stay: the new images paint the same story
        if (path.is_file() and path.name not in ('illustrations.json','prompting.json','story.json','reference-choices.json','reference-choices.json.lock')
                or story and path.name=='reference-choices.json'
                or story and path.name=='story.json' or references and path.name=='entities'):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Artwork source leaves the project.')
            archive.mkdir(exist_ok=True);shutil.move(str(path),str(archive/path.name))
    if (folder/'candidates').is_dir():
        if (folder/'candidates').is_symlink() or not (folder/'candidates').resolve().is_relative_to(root):
            raise ValueError('Candidate archive path leaves the project.')
        archive.mkdir(exist_ok=True);shutil.move(str(folder/'candidates'),str(archive/'candidates'))
