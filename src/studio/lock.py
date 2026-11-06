"""One lock for every job's state, shared by request handlers, run threads and timers."""
import threading

LOCK = threading.RLock()
