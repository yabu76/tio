#!/usr/bin/env python3

import time
import os
import tempfile
from _test_runner import TioSession

def test_hook_iorecv_default_behavior_unchanged():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
-- Echo back on receiving here.
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"A\x00B")
        session.wait_stdout(b"A\x00B")


def test_hook_iorecv_replacement_is_binary_safe():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return "X\\0Y"
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"abc")
        session.wait_stdout(b"X\x00Y")


def test_hook_iorecv_drop_chunk():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return ""
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"drop")
        assert session.read_stdout(0.4) == b""


def test_hook_iorecv_callback_error_disables_filter():
    script = """
tio.alwaysecho = false
local first = true
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    if first then
        first = false
        error("boom")
    end
    return "filtered"
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY", mute=False) as session:
        session.write_serial(b"GO")
        session.write_serial(b"first")
        # output = session.wait_stdout(b"first")
        output = session.wait_stdout(rb".*")
        assert b"hook_filter failed" in output

        session.drain_stdout()
        session.write_serial(b"second")
        output = session.wait_stdout(b"second")
        assert b"filtered" not in output


def test_hook_iorecv_non_string_return_disables_filter_without_coercion():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return 123
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY", mute=False) as session:
        session.write_serial(b"GO")
        session.write_serial(b"first")
        output = session.wait_stdout(b"first")
        assert b"returned number" in output
        assert b"123" not in output

        session.drain_stdout()
        session.write_serial(b"second")
        output = session.wait_stdout(b"second")
        assert b"123" not in output


def test_hook_iorecv_nil_argument_disables_filter():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return "filtered"
end)
tio.set_hook(tio.C.HK_IO_RECEIVE, nil)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"raw")
        output = session.wait_stdout(b"raw")
        assert b"filtered" not in output


def test_hook_iorecv_new_filter_replaces_old_filter():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return "old"
end)
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return "new"
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"raw")
        output = session.wait_stdout(b"new")
        assert b"old" not in output


def test_hook_iorecv_filter_closure_state_persists_across_chunks():
    script = """
tio.alwaysecho = false
local count = 0
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    count = count + 1
    return tostring(count) .. ":" .. data
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"A")
        session.wait_stdout(b"1:A")

        session.drain_stdout()
        session.write_serial(b"B")
        session.wait_stdout(b"2:B")


def test_hook_iorecv_self_disabling_filter_uses_current_result_then_turns_off():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    tio.set_hook(tio.C.HK_IO_RECEIVE, nil)
    return (data:gsub("raw", "once"))
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"raw")
        session.wait_stdout(b"once")

        session.drain_stdout()
        session.write_serial(b"raw")
        output = session.wait_stdout(b"raw")
        assert b"once" not in output


def test_hook_iorecv_socket_and_log_receive_filtered_output():
    script = """
tio.alwaysecho = false
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    return (data:gsub("raw", "filtered"))
end)
tio.write("READY")
local go = tio.read(2, 1000)
tio.alwaysecho = true
"""
    with tempfile.TemporaryDirectory() as tmp:
        socket_path = os.path.join(tmp, "tio.sock")
        log_path = os.path.join(tmp, "tio.log")
        log = b""

        with TioSession(script, ready=b"READY", log_path=log_path, socket_path=socket_path) as session:
            session.write_serial(b"GO")
            session.write_serial(b"raw")
            session.wait_stdout(b"filtered")
            session.wait_socket(b"filtered")

        with open(log_path, "rb") as log_file:
            log = log_file.read()

        assert b"filtered" in log
        assert b"raw" not in log


HOOK_TESTS = [
    test_hook_iorecv_default_behavior_unchanged,
    test_hook_iorecv_replacement_is_binary_safe,
    test_hook_iorecv_drop_chunk,
    test_hook_iorecv_callback_error_disables_filter,
    test_hook_iorecv_non_string_return_disables_filter_without_coercion,
    test_hook_iorecv_nil_argument_disables_filter,
    test_hook_iorecv_new_filter_replaces_old_filter,
    test_hook_iorecv_filter_closure_state_persists_across_chunks,
    test_hook_iorecv_self_disabling_filter_uses_current_result_then_turns_off,
    test_hook_iorecv_socket_and_log_receive_filtered_output,
]
