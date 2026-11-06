"""Illustration files on disk: the active run, gallery, metadata, review state, queues and greenscreen mattes."""
from core.progress import on_artifact
from artwork.gallery import publish_artifact

# Every artwork progress event refreshes Studio's live gallery, in whichever process reports it.
on_artifact(publish_artifact)
