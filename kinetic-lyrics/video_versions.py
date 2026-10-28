"""Read-only enumeration of current and archived Studio exports."""

from pathlib import Path
import json


def video_versions(folder, url_for):
    folder = Path(folder)
    result = []
    current = folder / "video.mp4"
    paths = ([current] if current.is_file() else []) + sorted(
        (folder / "history").glob("*.mp4"), reverse=True
    )
    for path in paths:
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                continue
            stat = path.stat()
            result.append(
                dict(
                    id=(
                        "current"
                        if path == current
                        else path.relative_to(folder).as_posix()
                    ),
                    url=url_for(path),
                    name=path.name,
                    current=path == current,
                    modified=stat.st_mtime,
                    bytes=stat.st_size,
                )
            )
        except FileNotFoundError:
            continue
    return sorted(
        result, key=lambda item: (item["current"], item["modified"]), reverse=True
    )


def remaining_changes(folder, dirty, revisions, indices=None):
    """Clear only changes whose selected image matches what was rendered."""
    import hashlib

    folder = Path(folder)
    if not revisions:return list(dirty)
    from active_artwork import select_manifest
    try:manifest=select_manifest(folder)
    except ValueError:return list(dirty)
    from lyric_placement import cached_placement, revision_matches
    try:
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        canvas = config["width"], config["height"]
    except (OSError, ValueError, KeyError):
        canvas = None
    remaining = []
    for index in dirty:
        if indices is not None and index not in indices:
            remaining.append(index)
            continue
        image = manifest.parent / f"{index:03d}.png"
        try:
            placement = cached_placement(image, *canvas) if canvas else None
            matches = revision_matches(
                revisions.get(str(index)),
                hashlib.sha256(image.read_bytes()).hexdigest(),
                placement,
            )
        except OSError:
            matches = False
        if not matches:
            remaining.append(index)
    return remaining


def verified_changes(folder, dirty=()):
    folder = Path(folder)
    video = folder / "video.mp4"
    try:
        metadata = json.loads(
            video.with_suffix(".render.json").read_text(encoding="utf-8")
        )
        if metadata.get("video_mtime_ns") != video.stat().st_mtime_ns:
            return list(dirty), False
        revisions = metadata["artwork_revisions"]
        if not isinstance(revisions, dict):
            return list(dirty), False
        indices = sorted(set(dirty) | {int(index) for index in revisions})
        return remaining_changes(folder, indices, revisions), True
    except (OSError, ValueError, KeyError, TypeError):
        return list(dirty), False


def write_render_metadata(video, revisions, start=0.0, end=None):
    video = Path(video)
    data = dict(
        video_mtime_ns=video.stat().st_mtime_ns,
        artwork_revisions=revisions,
        start=start,
        end=end,
    )
    target = video.with_suffix(".render.json")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(target)


def archive_video(video):
    import shutil
    import time

    video = Path(video)
    if not video.is_file():return None
    history = video.parent / "history"
    history.mkdir(exist_ok=True)
    archived = history / f"video-{time.time_ns()}.mp4"
    temporary=archived.with_suffix('.mp4.part')
    shutil.copy2(video, temporary)
    metadata = video.with_suffix(".render.json")
    if metadata.is_file():
        shutil.copy2(metadata, archived.with_suffix(".render.json"))
    temporary.replace(archived)
    return archived


def promote_render_metadata(source, video, indices=None):
    """Keep provenance in step with the exact full or partial export installed."""
    source, video = Path(source), Path(video)
    fresh = json.loads(source.with_suffix(".render.json").read_text(encoding="utf-8"))
    if indices is None:
        revisions = fresh["artwork_revisions"]
    else:
        try:
            revisions = json.loads(
                video.with_suffix(".render.json").read_text(encoding="utf-8")
            )["artwork_revisions"]
        except (OSError, ValueError, KeyError):
            revisions = {}
        for index in indices:
            if str(index) in fresh["artwork_revisions"]:
                revisions[str(index)] = fresh["artwork_revisions"][str(index)]
    write_render_metadata(video, revisions)
