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


def read_fd(fd, timeout):
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
        except OSError:
            break

        if not chunk:
            break

        chunks.append(chunk)

    return b"".join(chunks)


def read_socket(sock, timeout):
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

        if not chunk:
            break

        chunks.append(chunk)

    return b"".join(chunks)


def wait_for_match(read_func, expected, timeout=3):
    pattern = re.compile(expected)
    end = time.monotonic() + timeout
    data = b""

    while time.monotonic() < end:
        data += read_func(0.05)
        if pattern.search(data):
            return data

    raise AssertionError("timed out waiting for %r in %r" % (expected, data))


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

        self.serial_master, serial_slave = pty.openpty()
        self.stdin_master, stdin_slave = pty.openpty()
        # set_nonblocking(self.serial_master) -- python's outbound is blocking for buffering.
        # set_nonblocking(self.stdin_master) -- python's outbound is blocking for buffering.

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

        os.close(serial_slave)
        os.close(stdin_slave)
        # set_nonblocking(self.proc.stdout.fileno()) -- tio's stdout is blocking for buffering.

        if socket_path is not None:
            self.client = connect_unix_socket(socket_path)
            time.sleep(0.2)

        self.drain_stdout() # cleaning tio's stdout before receiving 'ready'

        if ready is not None:
            wait_for_match(
                lambda timeout: read_fd(self.serial_master, timeout),
                ready,
            )

    def wait_stdout(self, expected, timeout=3.0):
        progress("WAIT stdout: %r" % expected)

        data = wait_for_match(
            lambda t: read_fd(self.proc.stdout.fileno(), t),
            expected,
            timeout,
        )
        self.stdout += data
        progress("RX stdout: %r" % data)
        return data

    def read_stdout(self, timeout=0.3):
        data = read_fd(self.proc.stdout.fileno(), timeout)
        self.stdout += data
        return data

    def drain_stdout(self):
        self.stdout += read_fd(self.proc.stdout.fileno(), 0.1)
        self.stdout = b""

    def write_stdin(self, data):
        progress("IN stdin: %r" % data)
        os.write(self.stdin_master, data)

    def wait_serial(self, expected, timeout=3):
        progress("WAIT serial: %r" % expected)

        data = wait_for_match(
            lambda t: read_fd(self.serial_master, t),
            expected,
            timeout,
        )
        self.serial_rx += data
        progress("RX serial: %r" % data)
        return data

    def read_serial(self, timeout=3):
        data = read_fd(self.serial_master, timeout)
        self.serial_rx += data
        return self.serial_rx

    def drain_serial(self):
        self.serial_rx += read_fd(self.serial_master, 0.1)
        self.serial_rx = b""

    def write_serial(self, data, verbose_off=True):
        if not verbose_off:
            progress("TX serial: %r" % data)
        os.write(self.serial_master, data)

    def wait_socket(self, expected, timeout=3):
        if self.client is None:
            raise AssertionError("no socket client")
        progress("WAIT socket: %r (timeout=%ss)" % (expected, timeout))
        try:
            data = wait_for_match(
                lambda t: read_socket(self.client, t), expected, timeout
            )
        except AssertionError:
            progress("socket timeout")
            raise
        progress("RX socket: %r" % data)
        return data

    def close(self):
        if self.proc.poll() is None:
            try:
                os.write(self.stdin_master, PREFIX_KEY + b"q")
                self.proc.wait(timeout=3)
            except Exception as e:
                print(f"close error: {e}")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3)

        if self.client is not None:
            self.client.close()

        os.close(self.serial_master)
        os.close(self.stdin_master)
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
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
        except Exception:
            elapsed = test_elapsed()
            print("FAIL (%.2fs)" % elapsed, flush=True)
            print("        test: %s" % test.__name__, flush=True)
            raise
        else:
            elapsed = test_elapsed()
            passed += 1
            print("OK (%.2fs)" % elapsed, flush=True)

    elapsed = time.monotonic() - suite_start
    print("Passed: %d/%d (%.2fs)" % (passed, total, elapsed), flush=True)
