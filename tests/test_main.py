"""Tests for the top-level entry point ``main.py``.

The web command opens a real listening socket, which is slow and flaky in
tests, so ``backend.http_server.create_server`` is patched with a fake server.
The fake server records how it was called and lets a test drive
``serve_forever`` / ``server_close`` without touching the network.
"""

import contextlib
import io
import unittest
from unittest import mock

import main as main_module
from connector import TroubleBrewingAdapter


class FakeServer:
    def __init__(self, behavior="stop"):
        self.behavior = behavior
        self.serve_calls = 0
        self.close_calls = 0

    def serve_forever(self):
        self.serve_calls += 1
        if self.behavior == "stop":
            raise KeyboardInterrupt

    def server_close(self):
        self.close_calls += 1


class RunWebTests(unittest.TestCase):
    def setUp(self):
        self._redirects = contextlib.ExitStack()
        self._redirects.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self._redirects.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(self._redirects.close)

    def test_injects_real_adapter(self):
        fake = FakeServer(behavior="run")
        with mock.patch(
            "backend.http_server.create_server", return_value=fake
        ) as create:
            code = main_module.run_web("127.0.0.1", 8000)
        self.assertEqual(code, 0)
        create.assert_called_once()
        host, port = create.call_args.args
        self.assertEqual((host, port), ("127.0.0.1", 8000))
        adapter = create.call_args.kwargs.get("adapter")
        self.assertIsInstance(adapter, TroubleBrewingAdapter)
        self.assertEqual(fake.serve_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_keyboard_interrupt_closes_server(self):
        fake = FakeServer(behavior="stop")
        with mock.patch("backend.http_server.create_server", return_value=fake):
            code = main_module.run_web("127.0.0.1", 8000)
        self.assertEqual(code, 0)
        self.assertEqual(fake.close_calls, 1)

    def test_oserror_returns_one(self):
        with mock.patch(
            "backend.http_server.create_server", side_effect=OSError("in use")
        ):
            code = main_module.run_web("127.0.0.1", 8000)
        self.assertEqual(code, 1)


class DispatchTests(unittest.TestCase):
    def test_default_runs_tests(self):
        with mock.patch.object(main_module, "run_tests", return_value=0) as run:
            self.assertEqual(main_module.main([]), 0)
        run.assert_called_once()

    def test_test_command(self):
        with mock.patch.object(main_module, "run_tests", return_value=7) as run:
            self.assertEqual(main_module.main(["test"]), 7)
        run.assert_called_once()

    def test_demo_command(self):
        with mock.patch.object(main_module, "run_demo", return_value=3) as run:
            self.assertEqual(main_module.main(["demo"]), 3)
        run.assert_called_once()

    def test_web_command_forwards_host_and_port(self):
        with mock.patch.object(main_module, "run_web", return_value=0) as run:
            self.assertEqual(
                main_module.main(["web", "--host", "0.0.0.0", "--port", "9000"]), 0
            )
        run.assert_called_once_with("0.0.0.0", 9000)


if __name__ == "__main__":
    unittest.main()
