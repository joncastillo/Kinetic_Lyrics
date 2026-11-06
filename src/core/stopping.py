"""Stopping GPU work politely. Killing a worker in the middle of its GPU work reset the display driver: every app
drawing on the card lost it, and Chrome went white. So Cancel asks first: the studio writes the file named by
KINETIC_STOP_FILE (each run has its own, handed down to the workers it starts), and a worker that finds it leaves at its
next step and releases the card itself. studio.server.finish_stop forces only what has not left in time."""
import os

STOP_ENV = 'KINETIC_STOP_FILE'
STOPPED_CODE = 3


class Stopped(SystemExit):
    """Leaves the process like an exit, so `except Exception` around a step cannot take it for a failure and carry on."""
    def __init__(self):
        super().__init__(STOPPED_CODE)


def stop_requested():
    path = os.environ.get(STOP_ENV)
    return bool(path) and os.path.exists(path)


def check_stop():
    if stop_requested():
        print('Stopping: the run was cancelled.', flush=True)
        raise Stopped()


def stop_at_steps(pipe):
    """Check before every pass of a pipeline's transformer, which is every step of every image and video model, whether
    or not the pipeline takes a step callback."""
    model = getattr(pipe, 'transformer', None)
    if model is not None:
        model.register_forward_pre_hook(lambda module, args: check_stop())
