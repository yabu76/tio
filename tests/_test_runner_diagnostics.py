#!/usr/bin/env python3
"""Unit tests for the diagnostic features in _test_runner.py.

Place this file next to _test_runner.py and run:

    python3 test_runner_diagnostics.py

These tests do not start tio. They exercise the runner's wait/error handling
and its real pipe/socket EOF handling.
"""

import os
import socket
import sys
import unittest
from pathlib import Path

# _test_runner.py expects the tio executable as argv[1], although these tests
# exercise its helpers without starting tio.
original_argv = sys.argv[:]
runner_path = Path(__file__).with_name("_test_runner.py")
sys.path.insert(0, str(runner_path.parent))
sys.argv = [str(runner_path), os.devnull]
try:
    import _test_runner as runner
finally:
    sys.argv = original_argv


class FakeProcess:
    def __init__(self, status=None):
        self.status = status

    def poll(self):
        return self.status


class RunnerDiagnosticTests(unittest.TestCase):
    def assert_wait_error(self, callback, reason):
        with self.assertRaises(runner.WaitError) as caught:
            callback()
        error = caught.exception
        self.assertIn(reason, str(error))
        return error

    def test_timeout_reports_channel_expected_and_process_state(self):
        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                lambda _timeout: b"", b"READY", timeout=0.02,
                channel="serial", process=FakeProcess(),
            ),
            "Timeout waiting for expected data",
        )
        message = str(error)
        self.assertEqual(error.channel, "serial")
        self.assertEqual(error.expected, b"READY")
        self.assertEqual(error.received, b"")
        self.assertIn("Channel:  serial", message)
        self.assertIn("Expected: b'READY'", message)
        self.assertIn("Received: <no data>", message)
        self.assertIn("tio process: running", message)

    def test_stream_closed_is_distinguished_from_timeout(self):
        def closed_reader(_timeout):
            raise runner.StreamClosedError("test EOF")

        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                closed_reader, b"READY", timeout=1,
                channel="stdout", process=FakeProcess(),
            ),
            "Stream closed while waiting",
        )
        self.assertEqual(error.channel, "stdout")
        self.assertIn("test EOF", str(error))

    def test_stream_closed_after_process_exit_reports_exit_status(self):
        def closed_reader(_timeout):
            raise runner.StreamClosedError("file descriptor reached EOF")

        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                closed_reader, b"READY", timeout=1,
                channel="stdout", process=FakeProcess(status=17),
            ),
            "tio process exited and the stream was closed",
        )
        self.assertEqual(error.process_status, 17)
        self.assertIn("status=17", str(error))

    def test_process_exit_without_stream_eof_reports_exit_status(self):
        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                lambda _timeout: b"", b"READY", timeout=1,
                channel="serial", process=FakeProcess(status=23),
            ),
            "tio process exited before expected data arrived",
        )
        self.assertEqual(error.process_status, 23)
        self.assertIn("status=23", str(error))

    def test_oserror_is_reported_as_io_error(self):
        def broken_reader(_timeout):
            raise OSError(5, "simulated I/O failure")

        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                broken_reader, b"READY", timeout=1,
                channel="socket", process=FakeProcess(),
            ),
            "I/O error while waiting",
        )
        self.assertIsInstance(error.io_error, OSError)
        self.assertIn("simulated I/O failure", str(error))

    def test_received_data_is_preserved_when_wait_times_out(self):
        chunks = iter([b"partial-", b"data"])

        def reader(_timeout):
            try:
                return next(chunks)
            except StopIteration:
                return b""

        session = runner.TioSession.__new__(runner.TioSession)
        session.history = []
        session.started_at = runner.time.monotonic()

        error = self.assert_wait_error(
            lambda: runner.wait_for_match(
                reader, b"NEVER", timeout=0.03, channel="serial",
                process=FakeProcess(), session=session,
            ),
            "Timeout waiting for expected data",
        )
        self.assertEqual(error.received, b"partial-data")
        self.assertIn("partial-data", str(error))
        self.assertTrue(any(
            "RX" in item and "serial" in item for item in session.history
        ))

    def test_read_fd_reports_eof(self):
        read_fd, write_fd = os.pipe()
        try:
            os.close(write_fd)
            with self.assertRaises(runner.StreamClosedError):
                runner.read_fd(read_fd, 0.1)
        finally:
            os.close(read_fd)

    def test_read_socket_reports_peer_disconnect(self):
        local, peer = socket.socketpair()
        try:
            local.setblocking(False)
            peer.close()
            with self.assertRaises(runner.StreamClosedError):
                runner.read_socket(local, 0.1)
        finally:
            local.close()

    def test_history_is_bounded_to_100_entries(self):
        session = runner.TioSession.__new__(runner.TioSession)
        session.history = []
        session.started_at = runner.time.monotonic()
        for index in range(105):
            session._record("TX", "serial", f"message-{index}")

        self.assertEqual(len(session.history), 100)
        self.assertIn("message-5", session.history[0])
        self.assertIn("message-104", session.history[-1])

    def test_diagnostic_shows_only_the_last_20_history_entries(self):
        session = runner.TioSession.__new__(runner.TioSession)
        session.proc = FakeProcess()
        session.stdout = b"stdout-buffer"
        session.serial_rx = b"serial-buffer"
        session.history = [f"event-{index}" for index in range(25)]

        diagnostic = session.diagnostic()
        self.assertIn("tio process: running", diagnostic)
        self.assertIn("stdout-buffer", diagnostic)
        self.assertIn("serial-buffer", diagnostic)
        self.assertIn("event-5", diagnostic)
        self.assertIn("event-24", diagnostic)
        self.assertNotIn("event-4", diagnostic)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
