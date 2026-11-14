import logging
import queue
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

log = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000
_STOP = object()


class Dispatcher(ABC):
    @abstractmethod
    def submit(self, job: Callable[[], None]) -> None:
        ...


class ImmediateDispatcher(Dispatcher):
    """Runs jobs straight away. For tests only."""

    def submit(self, job):
        job()


class BackgroundDispatcher(Dispatcher):
    """Runs jobs on one worker thread, in order.

    P1's EventBus is synchronous, so a handler runs inside the user's request.
    Queueing here means a slow mail server can never delay "Resolve".
    """

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE):
        self._jobs: queue.Queue = queue.Queue(queue_size)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="notifications", daemon=True
            )
            self._thread.start()

    def submit(self, job):
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            log.error("Notification queue is full; dropping a job")

    def wait_until_idle(self) -> None:
        self._jobs.join()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._jobs.put(_STOP)
        self._thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is _STOP:
                    return
                job()
            except Exception:
                log.exception("Notification job failed")
            finally:
                self._jobs.task_done()
