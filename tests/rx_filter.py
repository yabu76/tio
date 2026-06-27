#!/usr/bin/env python3

import os
import pty
import select
import socket
import subprocess
import sys
import tempfile
import time


if os.name != "posix":
    sys.exit(77)


TIO = sys.argv[1]
PREFIX_KEY = b"\x14"


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


def wait_for_contains(read_func, expected, timeout=3):
    end = time.monotonic() + timeout
    data = b""

    while time.monotonic() < end:
        data += read_func(0.05)
        if expected in data:
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
    def __init__(self, script, mute=True, log_path=None, socket_path=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = None
        self.stdout = b""

        self.serial_master, serial_slave = pty.openpty()
        self.stdin_master, stdin_slave = pty.openpty()
        set_nonblocking(self.serial_master)
        set_nonblocking(self.stdin_master)

        script_path = os.path.join(self.tmp.name, "script.lua")
        with open(script_path, "w", encoding="utf-8") as script_file:
            script_file.write(script)
            script_file.write("\ntio.write(\"R\")\n")

        env = os.environ.copy()
        env["HOME"] = self.tmp.name
        env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, "xdg")

        args = [
            TIO,
            "--no-reconnect",
            "--baudrate",
            "9600",
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
        set_nonblocking(self.proc.stdout.fileno())

        if socket_path is not None:
            self.client = connect_unix_socket(socket_path)
            time.sleep(0.2)

        wait_for_contains(lambda timeout: read_fd(self.serial_master, timeout), b"R")
        self.drain_stdout()

    def drain_stdout(self):
        self.stdout += read_fd(self.proc.stdout.fileno(), 0.1)
        self.stdout = b""

    def write_serial(self, data):
        os.write(self.serial_master, data)

    def wait_stdout(self, expected, timeout=3):
        self.stdout += wait_for_contains(lambda t: read_fd(self.proc.stdout.fileno(), t), expected, timeout)
        return self.stdout

    def read_stdout(self, timeout=0.3):
        self.stdout += read_fd(self.proc.stdout.fileno(), timeout)
        return self.stdout

    def wait_socket(self, expected, timeout=3):
        if self.client is None:
            raise AssertionError("no socket client")
        return wait_for_contains(lambda t: read_socket(self.client, t), expected, timeout)

    def close(self):
        if self.proc.poll() is None:
            try:
                os.write(self.stdin_master, PREFIX_KEY + b"q")
                self.proc.wait(timeout=3)
            except Exception:
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


def test_default_behavior_unchanged():
    with TioSession("-- no rx filter registered") as session:
        session.write_serial(b"A\x00B")
        session.wait_stdout(b"A\x00B")


def test_replacement_is_binary_safe():
    script = """
tio.rx_filter(function(data)
    return "X\\0Y"
end)
"""
    with TioSession(script) as session:
        session.write_serial(b"abc")
        session.wait_stdout(b"X\x00Y")


def test_drop_chunk():
    script = """
tio.rx_filter(function(data)
    return nil
end)
"""
    with TioSession(script) as session:
        session.write_serial(b"drop")
        assert session.read_stdout(0.4) == b""


def test_callback_error_disables_filter():
    script = """
local first = true
tio.rx_filter(function(data)
    if first then
        first = false
        error("boom")
    end
    return "filtered"
end)
"""
    with TioSession(script, mute=False) as session:
        session.write_serial(b"first")
        output = session.wait_stdout(b"first")
        assert b"rx_filter failed" in output

        session.drain_stdout()
        session.write_serial(b"second")
        output = session.wait_stdout(b"second")
        assert b"filtered" not in output


def test_non_string_return_disables_filter_without_coercion():
    script = """
tio.rx_filter(function(data)
    return 123
end)
"""
    with TioSession(script, mute=False) as session:
        session.write_serial(b"first")
        output = session.wait_stdout(b"first")
        assert b"returned number" in output
        assert b"123" not in output

        session.drain_stdout()
        session.write_serial(b"second")
        output = session.wait_stdout(b"second")
        assert b"123" not in output


def test_nil_argument_disables_filter():
    script = """
tio.rx_filter(function(data)
    return "filtered"
end)
tio.rx_filter(nil)
"""
    with TioSession(script) as session:
        session.write_serial(b"raw")
        output = session.wait_stdout(b"raw")
        assert b"filtered" not in output


def test_new_filter_replaces_old_filter():
    script = """
tio.rx_filter(function(data)
    return "old"
end)
tio.rx_filter(function(data)
    return "new"
end)
"""
    with TioSession(script) as session:
        session.write_serial(b"raw")
        output = session.wait_stdout(b"new")
        assert b"old" not in output


def test_filter_closure_state_persists_across_chunks():
    script = """
local count = 0
tio.rx_filter(function(data)
    count = count + 1
    return tostring(count) .. ":" .. data
end)
"""
    with TioSession(script) as session:
        session.write_serial(b"A")
        session.wait_stdout(b"1:A")

        session.drain_stdout()
        session.write_serial(b"B")
        session.wait_stdout(b"2:B")


def test_self_disabling_filter_uses_current_result_then_turns_off():
    script = """
tio.rx_filter(function(data)
    tio.rx_filter(nil)
    return (data:gsub("raw", "once"))
end)
"""
    with TioSession(script) as session:
        session.write_serial(b"raw")
        session.wait_stdout(b"once")

        session.drain_stdout()
        session.write_serial(b"raw")
        output = session.wait_stdout(b"raw")
        assert b"once" not in output


def test_socket_and_log_receive_filtered_output():
    script = """
tio.rx_filter(function(data)
    return (data:gsub("raw", "filtered"))
end)
"""
    with tempfile.TemporaryDirectory() as tmp:
        socket_path = os.path.join(tmp, "tio.sock")
        log_path = os.path.join(tmp, "tio.log")

        with TioSession(script, log_path=log_path, socket_path=socket_path) as session:
            session.write_serial(b"raw")
            session.wait_stdout(b"filtered")
            session.wait_socket(b"filtered")

        with open(log_path, "rb") as log_file:
            log = log_file.read()

        assert b"filtered" in log
        assert b"raw" not in log


def main():
    tests = [
        test_default_behavior_unchanged,
        test_replacement_is_binary_safe,
        test_drop_chunk,
        test_callback_error_disables_filter,
        test_non_string_return_disables_filter_without_coercion,
        test_nil_argument_disables_filter,
        test_new_filter_replaces_old_filter,
        test_filter_closure_state_persists_across_chunks,
        test_self_disabling_filter_uses_current_result_then_turns_off,
        test_socket_and_log_receive_filtered_output,
    ]

    for test in tests:
        test()


if __name__ == "__main__":
    main()
