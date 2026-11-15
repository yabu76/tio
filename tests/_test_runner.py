#!/usr/bin/env python3

# Common test infrastructure for tio e2e tests.

#
#   master                                            slave
# ┌───────────┐                        ┌────────────┐
# │      e2e_test.py     │                        │         tio            │
# │                      │                        │                        │
# │ write_serial() ───┼─── serial ────►│ tio.expect(),tio.read()│
# │                      │                        │                        │
# │ wait_serial()  ◄──┼─── serial ─────┤ tio.write()            │
# │                      │                        │                        │
# │ write_stdin()  ───┼─── stdin  ────►│ key input              │
# │                      │                        │                        │
# │ wait_stdout()  ◄──┼─── stdout ─────┤ echo back, print()     │
# │                      │                        │                        │
# │ wait_socket()  ◄──┼─── socket ─────┤ echo back              │
# │                      │                        │                        │
# └───────────┘                        └────────────┘
#

import os
import pty
import select
import socket
import subprocess
import sys
import tempfile
import time
import re


if os.name != "posix":
    sys.exit(77)


TIO = sys.argv[1]
VERBOSE = "--verbose" in sys.argv[2:]
PREFIX_KEY = b"\x14" # Ctrl-t

_current_test = None
_current_test_start = None


def progress(message):
    if VERBOSE:
        print("    " + message, flush=True)


def set_current_test(name):
    global _current_test, _current_test_start
    _current_test = name
    _current_test_start = time.monotonic()


def test_elapsed():
    if _current_test_start is None:
        return 0.0
    return time.monotonic() - _current_test_start


def set_nonblocking(fd):
    os.set_blocking(fd, False)


class StreamClosedError(Exception):
    """Raised when an input stream reaches EOF or its peer disappears."""


class WaitError(AssertionError):
    """A wait operation failed, with channel and process diagnostics."""

    def __init__(self, channel, expected, received, timeout, reason,
                 process_status=None, io_error=None):
        self.channel = channel
        self.expected = expected
        self.received = received
        self.timeout = timeout
        self.reason = reason
        self.process_status = process_status
        self.io_error = io_error

    def __str__(self):
        lines = [
            self.reason,
            f"  Channel:  {self.channel}",
            f"  Expected: {self.expected!r}",
            f"  Received: {self.received!r}" if self.received else
            "  Received: <no data>",
            f"  Timeout:  {self.timeout:.2f}s",
        ]
        if self.process_status is None:
            lines.append("  tio process: running")
        else:
            lines.append(
                f"  tio process: exited (status={self.process_status})"
            )
        if self.io_error is not None:
            lines.append(f"  I/O error: {self.io_error}")
        return "\n".join(lines)


def read_fd(fd, timeout):
    """Read available bytes; distinguish an idle stream from a closed one."""
    end = time.monotonic() + timeout
    chunks = []

    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break

        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            break

        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        except OSError as error:
            # Linux PTYs commonly report EIO after the slave side closes.
            raise StreamClosedError(
                f"read failed: {error}"
            ) from error

        if not chunk:
            raise StreamClosedError("file descriptor reached EOF")

        chunks.append(chunk)

    return b"".join(chunks)


def read_socket(sock, timeout):
    """Read available socket data; EOF means the peer disconnected."""
    end = time.monotonic() + timeout
    chunks = []

    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break

        readable, _, _ = select.select([sock], [], [], remaining)
        if not readable:
            break

        try:
            chunk = sock.recv(4096)
        except BlockingIOError:
            continue
        except OSError as error:
            raise StreamClosedError(
                f"socket receive failed: {error}"
            ) from error

        if not chunk:
            raise StreamClosedError("socket peer disconnected")

        chunks.append(chunk)

    return b"".join(chunks)


def wait_for_match(read_func, expected, timeout=3, channel="unknown",
                   process=None, session=None):
    pattern = re.compile(expected)
    start = time.monotonic()
    end = start + timeout
    data = b""

    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break

        try:
            chunk = read_func(min(0.05, remaining))
            if chunk:
                data += chunk
                if session is not None:
                    session._record("RX", channel, chunk)
                if pattern.search(data):
                    return data
        except StreamClosedError as error:
            status = process.poll() if process is not None else None
            reason = "Stream closed while waiting for expected data"
            if status is not None:
                reason = "tio process exited and the stream was closed"
            raise WaitError(
                channel, expected, data, timeout, reason,
                status, error,
            ) from error
        except OSError as error:
            status = process.poll() if process is not None else None
            raise WaitError(
                channel, expected, data, timeout, "I/O error while waiting",
                status, error,
            ) from error

        if process is not None:
            status = process.poll()
            if status is not None:
                raise WaitError(
                    channel, expected, data, timeout,
                    "tio process exited before expected data arrived",
                    status,
                )

    status = process.poll() if process is not None else None
    raise WaitError(
        channel, expected, data, timeout,
        "Timeout waiting for expected data",
        status,
    )

def connect_unix_socket(path, timeout=3):
    end = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < end:
        if os.path.exists(path):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(path)
                sock.setblocking(False)
                return sock
            except OSError as error:
                last_error = error
                sock.close()
        time.sleep(0.02)

    raise AssertionError("failed to connect to %s: %s" % (path, last_error))


class TioSession:
    def __init__(self, script, mute=True, log_path=None, socket_path=None,
                 ready=b"R"):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = None
        self.stdout = b""
        self.serial_rx = b""
        self.history = []
        self.started_at = time.monotonic()
        self.proc = None
        self.serial_master = None
        self.stdin_master = None

        try:
            self.serial_master, serial_slave = pty.openpty()
            self.stdin_master, stdin_slave = pty.openpty()
            # Keep the master's outbound side blocking to avoid partial writes.

            script_path = os.path.join(self.tmp.name, "script.lua")
            with open(script_path, "w", encoding="utf-8") as script_file:
                script_file.write(script)
                script_file.write("\ntio.write(\"R\")\n")

            env = os.environ.copy()
            env["HOME"] = self.tmp.name
            env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, "xdg")

            args = [
                TIO,
                "--local-echo",
                "--no-reconnect",
                "--baudrate",
                "115200",
                "--script-file",
                script_path,
            ]

            if mute:
                args.append("--mute")
            if log_path is not None:
                args += ["--log", "--log-file", log_path]
            if socket_path is not None:
                args += ["--socket", "unix:" + socket_path]

            args.append(os.ttyname(serial_slave))

            self.proc = subprocess.Popen(
                args,
                stdin=stdin_slave,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
            self._record("START", "process", " ".join(args))

            os.close(serial_slave)
            serial_slave = None
            os.close(stdin_slave)
            stdin_slave = None

            if socket_path is not None:
                try:
                    self.client = connect_unix_socket(socket_path)
                    self._record("CONNECTED", "socket", socket_path)
                    time.sleep(0.2)
                except Exception as error:
                    raise AssertionError(
                        f"SETUP_ERROR: unable to connect to socket "
                        f"{socket_path!r}: {error}; "
                        f"tio status={self.proc.poll()}"
                    ) from error

            # Discard startup chatter before waiting for the script marker.
            self.drain_stdout()

            if ready is not None:
                self._wait_ready(ready)
        except Exception:
            self.close()
            raise
        finally:
            # If setup failed before these descriptors were closed.
            for fd_name in ("serial_slave", "stdin_slave"):
                fd = locals().get(fd_name)
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _record(self, direction, channel, data):
        elapsed = time.monotonic() - self.started_at
        if isinstance(data, bytes):
            rendered = repr(data)
        else:
            rendered = str(data)
        self.history.append(
            f"[{elapsed:8.3f}] {direction:9s} {channel:7s} {rendered}"
        )
        # Bound memory use if a test produces a large amount of traffic.
        if len(self.history) > 100:
            del self.history[:-100]

    def _wait_ready(self, expected):
        progress("WAIT serial (startup): %r" % expected)
        data = wait_for_match(
            lambda timeout: read_fd(self.serial_master, timeout),
            expected,
            channel="serial (startup READY)",
            process=self.proc,
            session=self,
        )
        self.serial_rx += data
        progress("RX serial (startup): %r" % data)

    def _write(self, fd, data, channel, direction):
        try:
            os.write(fd, data)
        except OSError as error:
            self._record("ERROR", channel, error)
            raise AssertionError(
                f"I/O error writing to {channel}: {error}; "
                f"tio status={self.proc.poll() if self.proc else None}"
            ) from error
        self._record(direction, channel, data)

    def wait_stdout(self, expected, timeout=3.0):
        progress("WAIT stdout: %r" % expected)
        try:
            data = wait_for_match(
                lambda t: read_fd(self.proc.stdout.fileno(), t),
                expected,
                timeout,
                channel="stdout",
                process=self.proc,
                session=self,
            )
        except WaitError as error:
            self.stdout += error.received
            raise
        self.stdout += data
        progress("RX stdout: %r" % data)
        return data

    def read_stdout(self, timeout=0.3):
        try:
            data = read_fd(self.proc.stdout.fileno(), timeout)
        except StreamClosedError as error:
            raise AssertionError(
                f"stdout closed while reading; tio status={self.proc.poll()}: "
                f"{error}"
            ) from error
        self.stdout += data
        if data:
            self._record("RX", "stdout", data)
        return data

    def drain_stdout(self):
        try:
            data = read_fd(self.proc.stdout.fileno(), 0.1)
        except StreamClosedError as error:
            raise AssertionError(
                f"stdout closed during setup; tio status={self.proc.poll()}: "
                f"{error}"
            ) from error
        if data:
            self._record("DISCARD", "stdout", data)
        self.stdout = b""

    def write_stdin(self, data):
        progress("IN stdin: %r" % data)
        self._write(self.stdin_master, data, "stdin", "TX")

    def wait_serial(self, expected, timeout=3):
        progress("WAIT serial: %r" % expected)
        try:
            data = wait_for_match(
                lambda t: read_fd(self.serial_master, t),
                expected,
                timeout,
                channel="serial",
                process=self.proc,
                session=self,
            )
        except WaitError as error:
            self.serial_rx += error.received
            raise
        self.serial_rx += data
        progress("RX serial: %r" % data)
        return data

    def read_serial(self, timeout=3):
        try:
            data = read_fd(self.serial_master, timeout)
        except StreamClosedError as error:
            raise AssertionError(
                f"serial stream closed; tio status={self.proc.poll()}: {error}"
            ) from error
        self.serial_rx += data
        if data:
            self._record("RX", "serial", data)
        return self.serial_rx

    def drain_serial(self):
        try:
            data = read_fd(self.serial_master, 0.1)
        except StreamClosedError as error:
            raise AssertionError(
                f"serial stream closed while draining; "
                f"tio status={self.proc.poll()}: {error}"
            ) from error
        if data:
            self._record("DISCARD", "serial", data)
        self.serial_rx = b""

    def write_serial(self, data, verbose_off=True):
        if not verbose_off:
            progress("TX serial: %r" % data)
        self._write(self.serial_master, data, "serial", "TX")

    def wait_socket(self, expected, timeout=3):
        if self.client is None:
            raise AssertionError("SETUP_ERROR: no socket client")
        progress("WAIT socket: %r (timeout=%ss)" % (expected, timeout))
        try:
            data = wait_for_match(
                lambda t: read_socket(self.client, t),
                expected,
                timeout,
                channel="socket",
                process=self.proc,
                session=self,
            )
        except WaitError:
            raise
        progress("RX socket: %r" % data)
        return data

    def diagnostic(self):
        status = self.proc.poll() if self.proc is not None else None
        lines = [
            "  tio process: " + (
                "not started" if self.proc is None else
                "running" if status is None else f"exited (status={status})"
            )
        ]
        if self.stdout:
            lines.append(f"  stdout buffer: {self.stdout!r}")
        if self.serial_rx:
            lines.append(f"  serial buffer: {self.serial_rx!r}")
        if self.history:
            lines.append("  recent communication history:")
            lines.extend("    " + item for item in self.history[-20:])
        return "\n".join(lines)

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self._write(
                    self.stdin_master, PREFIX_KEY + b"q", "stdin", "TX"
                )
                self.proc.wait(timeout=3)
            except Exception as error:
                print(f"close error: {error}", file=sys.stderr, flush=True)
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3)
                except OSError:
                    pass

        if self.client is not None:
            try:
                self.client.close()
            except OSError:
                pass
            self.client = None

        for fd_name in ("serial_master", "stdin_master"):
            fd = getattr(self, fd_name, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_name, None)

        if self.tmp is not None:
            self.tmp.cleanup()
            self.tmp = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None:
            # Attach session-level context to failures raised inside a with block.
            diagnostic = self.diagnostic()
            if diagnostic:
                print("Session diagnostics:\n" + diagnostic,
                      file=sys.stderr, flush=True)
        self.close()



def run_tests(tests):
    total = len(tests)
    passed = 0
    suite_start = time.monotonic()

    print("Running %d tests%s..." % (
        total,
        " (verbose)" if VERBOSE else "",
    ), flush=True)

    for number, test in enumerate(tests, 1):
        set_current_test(test.__name__)
        print("[%02d/%02d] %s ... " % (
            number, total, test.__name__
        ), end="\n" if VERBOSE else "", flush=True)

        try:
            test()
        except Exception as error:
            elapsed = test_elapsed()
            print("FAIL (%.2fs)" % elapsed, flush=True)
            print("        test: %s" % test.__name__, flush=True)
            print("        error: %s" % error, flush=True)
            raise
        else:
            elapsed = test_elapsed()
            passed += 1
            print("OK (%.2fs)" % elapsed, flush=True)

    elapsed = time.monotonic() - suite_start
    print("Passed: %d/%d (%.2fs)" % (passed, total, elapsed), flush=True)
