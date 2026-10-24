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
    def __init__(self, name: str = "xupakata-worker"):
        self._jobs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()

    def submit(self, job) -> bool:
        """Encola una tarea; devuelve False si el trabajador ya se detuvo."""
        with self._lock:
            if self._stopped:
                return False
            self._jobs.put(job)
            return True

    def clear(self) -> None:
        """Descarta tareas que aún no han empezado."""
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                return

    def stop(self, timeout: float = 1.0) -> None:
        """Detiene el hilo tras la tarea en curso, sin esperar indefinidamente."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._jobs.put(_STOP)
        if self._thread.is_alive():
            self._thread.join(timeout)

    def wait_idle(self, timeout: float = 2.0) -> None:
        """Bloquea hasta que la cola se vacíe (solo pruebas y diagnósticos)."""
        if self._stopped:
            return
        deadline = threading.Event()
        if self.submit(deadline.set):
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
