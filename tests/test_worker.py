import threading
import time

from xupakata.worker import Worker


def test_ejecuta_en_orden():
    worker = Worker()
    done = []
    try:
        for index in range(5):
            worker.submit(lambda i=index: done.append(i))
        worker.wait_idle()
    finally:
        worker.stop()

    assert done == [0, 1, 2, 3, 4]


def test_una_tarea_fallida_no_mata_el_hilo():
    worker = Worker()
    done = []

    def boom():
        raise RuntimeError("fallo")

    try:
        worker.submit(boom)
        worker.submit(lambda: done.append("siguiente"))
        worker.wait_idle()
    finally:
        worker.stop()

    assert done == ["siguiente"]


def test_clear_descarta_pendientes():
    worker = Worker()
    started = threading.Event()
    release = threading.Event()
    done = []

    def slow():
        started.set()
        release.wait(2)

    worker.submit(slow)
    assert started.wait(2)
    worker.submit(lambda: done.append("descartada"))
    worker.clear()
    release.set()
    worker.wait_idle()

    assert done == []
    worker.stop()


def test_stop_termina_el_hilo():
    worker = Worker()
    worker.submit(lambda: None)
    worker.stop()

    assert not worker._thread.is_alive()


def test_no_acepta_tareas_tras_stop():
    worker = Worker()
    worker.stop()
    done = []

    assert worker.submit(lambda: done.append("tarde")) is False
    assert done == []


def test_stop_es_idempotente():
    worker = Worker()
    worker.stop()
    worker.stop()

    assert not worker._thread.is_alive()


def test_wait_idle_respeta_el_plazo():
    worker = Worker()
    release = threading.Event()
    worker.submit(lambda: release.wait(2))

    started = time.time()
    worker.wait_idle(timeout=0.05)
    assert time.time() - started < 1.5

    release.set()
    worker.stop()
