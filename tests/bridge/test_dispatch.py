"""Tests fuer den Dispatch -- inklusive der Thread-Affinitaet.

Die Annahme, Tests koennten Thread-Affinitaetsfehler nicht fangen, ist falsch.
Sie koennen es, wenn der Adapter sich selbst absichert: @main_thread_only macht
aus einem nicht-deterministischen Absturz irgendwo in Coin3D einen
deterministischen RuntimeError mit Stacktrace an der Aufrufstelle.
"""

import asyncio
import threading
import unittest

from freecad_bridge import dispatch
from freecad_bridge import state as bridge_state


@dispatch.main_thread_only
def _needs_main_thread():
    return "ausgefuehrt"


class MainThreadGuardTest(unittest.TestCase):
    def test_erlaubt_auf_hauptthread(self):
        self.assertEqual(_needs_main_thread(), "ausgefuehrt")

    def test_wirft_aus_worker_thread(self):
        captured = {}

        def worker():
            try:
                _needs_main_thread()
            except RuntimeError as exc:
                captured["error"] = exc

        thread = threading.Thread(target=worker, name="test-worker")
        thread.start()
        thread.join(5)

        self.assertIn("error", captured, "Der Guard hat den Fremdthread nicht bemerkt")
        message = str(captured["error"])
        self.assertIn("test-worker", message, "Der Threadname gehoert in die Meldung")
        self.assertIn("dispatch()", message, "Die Meldung muss den richtigen Weg nennen")

    def test_behaelt_metadaten(self):
        self.assertEqual(_needs_main_thread.__name__, "_needs_main_thread")


class DispatchFastPathTest(unittest.IsolatedAsyncioTestCase):
    """Ohne QApplication laeuft alles inline.

    Ohne diesen Fast-Path liefe jeder Test in den Timeout: es gibt headless
    niemanden, der die Queue leert.
    """

    async def test_fuehrt_inline_aus(self):
        self.assertTrue(dispatch.fast_path_available())
        result = await dispatch.dispatch(lambda: 21 * 2)
        self.assertEqual(result, 42)

    async def test_reicht_ausnahme_durch(self):
        def boom():
            raise ValueError("kaputt")

        with self.assertRaises(ValueError):
            await dispatch.dispatch(boom)

    async def test_lehnt_ab_waehrend_shutdown(self):
        state = bridge_state.get_state()
        state.shutting_down = True
        try:
            with self.assertRaises(dispatch.ShuttingDownError):
                await dispatch.dispatch(lambda: 1)
        finally:
            state.shutting_down = False


class FastPathThreadTest(unittest.TestCase):
    def test_kein_schnellweg_ausserhalb_des_hauptthreads(self):
        """Headless darf der Server-Thread FreeCAD NICHT direkt ausfuehren.

        Frueher galt "kein QApplication -> inline". Der echte Server lief dann
        headless FreeCAD-Code im Server-Thread aus; @main_thread_only fing es.
        """
        seen = {}

        def worker():
            seen["fast"] = dispatch.fast_path_available()

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(seen["fast"])
        self.assertTrue(dispatch.fast_path_available(), "auf dem Hauptthread schon")


class QueueTeardownTest(unittest.TestCase):
    def test_clear_queue_loest_wartende_auf(self):
        """Wartende Tasks werden aufgeloest, nicht in den Timeout geschickt."""
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            task = dispatch._Task(lambda: None, dispatch.WRITE, loop, future, None)
            dispatch._request_queue.put(task)

            freed = dispatch.clear_queue("Test")
            self.assertGreaterEqual(freed, 1)
            self.assertTrue(task.cancel.is_set())

            loop.run_until_complete(asyncio.sleep(0))
            self.assertTrue(future.done())
            self.assertIsInstance(future.exception(), dispatch.ShuttingDownError)
        finally:
            loop.close()
            dispatch.clear_queue()


class GuardTest(unittest.TestCase):
    def test_headless_blockiert_nicht(self):
        """Ohne GUI gibt es nichts zu schuetzen -- Schreiben muss laufen."""
        self.assertIsNone(dispatch.gui_block_reason())


if __name__ == "__main__":
    unittest.main()
