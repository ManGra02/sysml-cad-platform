"""Tests for the dispatch -- including thread affinity.

The assumption that tests cannot catch thread-affinity errors is wrong.
They can, if the adapter guards itself: @main_thread_only turns a
non-deterministic crash somewhere in Coin3D into a deterministic
RuntimeError with a stack trace at the call site.
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

        self.assertIn("error", captured, "The guard did not notice the foreign thread")
        message = str(captured["error"])
        self.assertIn("test-worker", message, "The thread name belongs in the message")
        self.assertIn("dispatch()", message, "The message must name the correct path")

    def test_behaelt_metadaten(self):
        self.assertEqual(_needs_main_thread.__name__, "_needs_main_thread")


class DispatchFastPathTest(unittest.IsolatedAsyncioTestCase):
    """Without a QApplication everything runs inline.

    Without this fast path every test would run into the timeout: headless,
    there is nobody to drain the queue.
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
        """Headless, the server thread must NOT execute FreeCAD directly.

        The old rule was "no QApplication -> inline". The real server then ran
        FreeCAD code headless in the server thread; @main_thread_only caught it.
        """
        seen = {}

        def worker():
            seen["fast"] = dispatch.fast_path_available()

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(seen["fast"])
        self.assertTrue(dispatch.fast_path_available(), "but it is on the main thread")


class QueueTeardownTest(unittest.TestCase):
    def test_clear_queue_loest_wartende_auf(self):
        """Waiting tasks are resolved, not sent into the timeout."""
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
        """Without a GUI there is nothing to protect -- writing must work."""
        self.assertIsNone(dispatch.gui_block_reason())


if __name__ == "__main__":
    unittest.main()
