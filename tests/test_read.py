#!/usr/bin/env python3

from _test_runner import TioSession

import sys
import time

is_msys_runtime = (sys.platform == "msys" or sys.platform == "cygwin")

def test_read_exact_size():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local data = tio.read(5, 1000)
print("READ_EXACT:" .. tostring(data == "hello") .. ":" .. tostring(#data))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"hello")
        session.wait_stdout(b"READ_EXACT:true:5")


def test_read_larger_than_lua_buffer():
    script = """
tio.alwaysecho = false
tio.write("READY")
local data = tio.read(16384, 1000)
print("READ_LARGE:" .. tostring(data ~= nil and #data == 16384 and data:sub(1, 1) == "z" and data:sub(-1) == "z"))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"z" * 16384)
        session.wait_stdout(b"READ_LARGE:true")


def test_read_returns_available_data_without_waiting_for_full_size():
    # tio.read() returns as soon as some data is available, even when fewer
    # bytes than requested have been received. The timeout is only used while
    # waiting for the first byte.
    script = """
tio.alwaysecho = false
tio.write("READY")
local data = tio.read(10, 1000)
print("READ_PARTIAL:" .. tostring(data == "abc") .. ":" .. tostring(#data))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"abc")
        session.wait_stdout(b"READ_PARTIAL:true:3")


def test_read_timeout_without_data_returns_nil():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000) -- wait for read start timing
local data = tio.read(10, 150)
print("READ_TIMEOUT:" .. tostring(data == nil))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"READ_TIMEOUT:true")

def test_read_nowait_returns_available_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local data = tio.read(3, tio.C.NOWAIT)
print("READ_NOWAIT:" .. tostring(data == "xyz") .. ":" .. tostring(#data))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GOxyz")
        session.wait_stdout(b"READ_NOWAIT:true:3")

def test_read_nowait_without_data_returns_nil():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local data = tio.read(8, tio.C.NOWAIT)
print("READ_EMPTY:" .. tostring(data == nil))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"READ_EMPTY:true")


def test_read_size_one():
    script = """
tio.alwaysecho = false
tio.write("READY")
local data = tio.read(1, 1000)
print("READ_ONE:" .. tostring(data == "A"))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"ABC")
        session.wait_stdout(b"READ_ONE:true")


def test_read_size_limit_and_invalid_sizes():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local ok_max = pcall(tio.read, tio.C.READ_SIZE_MAX, tio.C.NOWAIT)
local ok_max_plus_one = pcall(tio.read, tio.C.READ_SIZE_MAX + 1, tio.C.NOWAIT)
local ok_zero = pcall(tio.read, 0, tio.C.NOWAIT)
local ok_negative = pcall(tio.read, -1, tio.C.NOWAIT)
local ok_table = pcall(tio.read, {}, tio.C.NOWAIT)
local ok_timeout = pcall(tio.read, 1, {})
print("READ_LIMIT:" .. tio.C.READ_SIZE_MAX
    .. ":" .. tostring(ok_max)
    .. ":" .. tostring(not ok_max_plus_one)
    .. ":" .. tostring(not ok_zero)
    .. ":" .. tostring(not ok_negative)
    .. ":" .. tostring(not ok_table)
    .. ":" .. tostring(not ok_timeout))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        cmax = 1024 * 1024  # tio.C.READ_SIZE_MAX
        expect_bstr = f"READ_LIMIT:{cmax}:true:true:true:true:true:true".encode()
        session.wait_stdout(expect_bstr)


def test_readline_returns_line_without_lf():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local line = tio.readline(1000)
print("LINE:" .. tostring(line == "hello\\r"))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"hello\r\n")
        session.wait_stdout(b"LINE:true")

def test_readline_empty_line():
    script = """
tio.alwaysecho = false
tio.write("READY")
local line = tio.readline(1000)
print("EMPTY_LINE:" .. tostring(line ~= nil) .. ":" .. tostring(line == ""))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"\n")
        session.wait_stdout(b"EMPTY_LINE:true:true")


def test_readline_reads_consecutive_lines():
    script = """
tio.alwaysecho = false
tio.write("READY")
local first = tio.readline(1000)
local second = tio.readline(1000)
print("LINES:" .. tostring(first == "one") .. ":" .. tostring(second == "two"))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"one\ntwo\n")
        session.wait_stdout(b"LINES:true:true")


def test_readline_timeout_returns_partial_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local line, partial = tio.readline(150)
print("LINE_TIMEOUT:" .. tostring(line == nil) .. ":" .. tostring(partial == "partial"))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"partial")
        session.wait_stdout(b"LINE_TIMEOUT:true:true")


def test_readline_nowait_without_data_returns_empty_partial():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local line, partial = tio.readline(tio.C.NOWAIT)
print("LINE_NOWAIT:" .. tostring(line == nil) .. ":" .. tostring(partial == ""))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"LINE_NOWAIT:true:true")


def test_readline_invalid_timeout_type():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local ok = pcall(tio.readline, {})
print("LINE_BAD_TIMEOUT:" .. tostring(not ok))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"LINE_BAD_TIMEOUT:true")


def test_readline_size_limit():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local line, partial = tio.readline(1000)
print("READLINE_LIMIT:"
    .. tio.C.READ_SIZE_MAX .. ":"
    .. tostring(line == nil) .. ":"
    .. tostring(partial ~= nil and #partial == tio.C.READ_SIZE_MAX))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        cmax = 1024 * 1024  # tio.C.READ_SIZE_MAX
        send_chunk = b"x" * 500
        session.write_serial(b"GO")
        for _ in range(cmax // len(send_chunk)):
            session.write_serial(send_chunk, verbose_off=True)
            if is_msys_runtime:
                time.sleep(0.02)
        for _ in range(cmax % len(send_chunk)):
            session.write_serial(b".", verbose_off=True)
        expect_bstr = f"READLINE_LIMIT:{cmax}:true:true".encode()
        session.wait_stdout(expect_bstr)

READ_TESTS = [
    test_read_exact_size,
    test_read_larger_than_lua_buffer,
    test_read_returns_available_data_without_waiting_for_full_size,
    test_read_timeout_without_data_returns_nil,
    test_read_nowait_returns_available_data,
    test_read_nowait_without_data_returns_nil,
    test_read_size_one,
    test_read_size_limit_and_invalid_sizes,
    test_readline_returns_line_without_lf,
    test_readline_empty_line,
    test_readline_reads_consecutive_lines,
    test_readline_timeout_returns_partial_data,
    test_readline_nowait_without_data_returns_empty_partial,
    test_readline_invalid_timeout_type,
    test_readline_size_limit,
]

#
# Due to its underlying architecture, the PTY in MSYS2 has a slow communication
# speed (43 kbps in my environment). Therefore, tests that involve handling large
# amounts of data are excluded from the MSYS2 environment.
#
if is_msys_runtime:
    READ_TESTS.remove(test_readline_size_limit)
