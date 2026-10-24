"""Cola de trabajo única para las operaciones de OpenRGB.

Solo el hilo auxiliar toca el SDK; nunca el hilo de GTK. Las tareas se
ejecutan en orden y pueden descartarse antes de empezar.
"""
import logging
import queue
import threading

logger = logging.getLogger(__name__)

_STOP = object()


class Worker:
    def __init__(self, name: str = "gnome-rgb-worker"):
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()

    def submit(self, job) -> None:
        self._jobs.put(job)

    def clear(self) -> None:
        """Descarta tareas que aún no han empezado."""
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                return

    def stop(self, timeout: float = 2.0) -> None:
        """Deja terminar lo que ya está en cola y espera a que el hilo acabe."""
        self._jobs.put(_STOP)
        if self._thread.is_alive():
            self._thread.join(timeout)

    def wait_idle(self, timeout: float = 2.0) -> None:
        """Bloquea hasta que la cola se vacíe (solo pruebas y diagnósticos)."""
        deadline = threading.Event()
        self._jobs.put(deadline.set)
        deadline.wait(timeout)

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is _STOP:
                return
            try:
                job()
            except Exception:
                logger.exception("tarea del trabajador falló")
