#!/usr/bin/env python3

import time

from _test_runner import TioSession

def test_expect_match():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("OK", 1000)
print(string.format("EXPECT:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"OK")
        session.wait_stdout(b"EXPECT:OK:OK:1:2")


def test_expect_capture_and_match_positions():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("VALUE:(%d+)", 1000)
print(string.format("CAPTURE:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"xxVALUE:123yy")
        session.wait_stdout(b"CAPTURE:123:xxVALUE:123yy:3:11")


def test_expect_timeout_returns_received_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local value, data, first, last = tio.expect("NEVER", 150)
print("TIMEOUT:" .. tostring(value == nil) .. ":" .. data .. ":" .. tostring(first == nil) .. ":" .. tostring(last == nil))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"abc")
        session.wait_stdout(b"TIMEOUT:true:abc:true:true")


def test_expect_timeout_with_empty_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local value, data = tio.expect("NEVER", 100)
print("EMPTY_TIMEOUT:" .. tostring(value == nil) .. ":" .. tostring(data == ""))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"EMPTY_TIMEOUT:true:true")


def test_expect_match_across_chunks():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("OK", 1000)
print(string.format("CROSS:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"O")
        time.sleep(0.05)
        session.write_serial(b"K")
        session.wait_stdout(b"CROSS:OK:OK:1:2")


def test_expect_match_with_preceding_and_trailing_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("OK", 1000)
print(string.format("SURROUND:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"abcOKxyz")
        session.wait_stdout(b"SURROUND:OK:abcOKxyz:4:5")


def test_expect_remaining_completes_pattern():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("PREFIX", 1000, "PRE")
print(string.format("REMAINING:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"FIX")
        session.wait_stdout(b"REMAINING:PREFIX:PREFIX:1:6")


def test_expect_remaining_already_matches_without_new_input():
    # The remaining buffer is already complete; no serial input should be needed.
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local value, data, first, last = tio.expect("OK", 100, "OK")
print("REMAINING_ONLY:" .. tostring(value == "OK") .. ":" .. data .. ":" .. tostring(first) .. ":" .. tostring(last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"REMAINING_ONLY:true:OK:1:2")


def test_expect_lua_pattern_and_capture():
    script = """
tio.alwaysecho = false
tio.write("READY")
local value, data, first, last = tio.expect("VALUE:%s+(%d+)", 1000)
print(string.format("PATTERN:%s:%s:%d:%d", value, data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"VALUE:   42")
        session.wait_stdout(b"PATTERN:42:VALUE:   42:1:11")


def test_expect_invalid_pattern_raises_lua_error():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local ok = pcall(tio.expect, "%", 100)
print("BAD_PATTERN:" .. tostring(not ok))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"x")
        session.wait_stdout(b"BAD_PATTERN:true")


def test_expect_invalid_argument_types_raise_lua_error():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local bad_pattern = pcall(tio.expect, {}, 100)
local bad_remaining = pcall(tio.expect, "OK", 100, {})
print("BAD_ARGS:" .. tostring(not bad_pattern) .. ":" .. tostring(not bad_remaining))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"xy")
        session.wait_stdout(b"BAD_ARGS:true:true")


def test_expect_multiple_calls_with_remaining_buffer():
    script = """
tio.alwaysecho = false
tio.write("READY")
local first, data1, _, last1 = tio.expect("ONE", 1000)
local second, data2, first2, last2 = tio.expect("TWO", 1000, data1:sub(last1 + 1))
print("SEQUENTIAL:" .. tostring(first == "ONE") .. ":" .. tostring(second == "TWO") .. ":" .. data2 .. ":" .. tostring(first2) .. ":" .. tostring(last2))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"ONETWO")
        session.wait_stdout(b"SEQUENTIAL:true:true:TWO:1:3")


def test_expects_first_pattern_and_positions():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures, data, first, last = tio.expects({"ERROR", "OK"}, 1000)
print(string.format("MATCH:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"ERROR")
        session.wait_stdout(b"MATCH:1:ERROR:ERROR:1:5")


def test_expects_second_pattern_with_capture():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures, data, first, last = tio.expects({"ERROR", "OK (%d+)"}, 1000)
print(string.format("MATCH:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"OK 123")
        session.wait_stdout(b"MATCH:2:123:OK 123:1:6")


def test_expects_timeout_returns_received_data():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local index, captures, data, first, last = tio.expects({"ERROR", "OK"}, 150)
print("TIMEOUT:" .. tostring(index == nil) .. ":" .. tostring(captures == nil) .. ":" .. data .. ":" .. tostring(first == nil) .. ":" .. tostring(last == nil))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"hello")
        session.wait_stdout(b"TIMEOUT:true:true:hello:true:true")


def test_expects_match_across_chunks():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures, data, first, last = tio.expects({"ERROR", "OK"}, 1000)
print(string.format("CROSS:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"O")
        time.sleep(0.05)
        session.write_serial(b"K")
        session.wait_stdout(b"CROSS:2:OK:OK:1:2")


def test_expects_earliest_completion_wins():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures, data, first, last = tio.expects({".*AAA", ".*BBB"}, 1000)
print(string.format("EARLIEST:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"xxBBByyAAA")
        session.wait_stdout(b"EARLIEST:2:xxBBB:xxBBByyAAA:1:5")


def test_expects_same_completion_uses_pattern_order():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures = tio.expects({"OK", "OK"}, 1000)
print("TIE:" .. tostring(index))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"OK")
        session.wait_stdout(b"TIE:1")


def test_expects_accepts_single_pattern_string():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local index, captures, data, first, last = tio.expects("OK", 1000)
print(string.format("SINGLE:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"OK")
        session.wait_stdout(b"SINGLE:1:OK:OK:1:2")


def test_expects_remaining_completes_pattern():
    script = """
tio.alwaysecho = false
tio.write("READY")
local index, captures, data, first, last = tio.expects({"PREFIX"}, 1000, "PRE")
print(string.format("REMAINING:%d:%s:%s:%d:%d", index, captures[1], data, first, last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"FIX")
        session.wait_stdout(b"REMAINING:1:PREFIX:PREFIX:1:6")


def test_expects_remaining_already_matches_without_new_input():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local index, captures, data, first, last = tio.expects({"OK"}, 100, "OK")
print("REMAINING_ONLY:" .. tostring(index == 1) .. ":" .. tostring(captures[1]) .. ":" .. data .. ":" .. tostring(first) .. ":" .. tostring(last))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"REMAINING_ONLY:true:OK:OK:1:2")


def test_expects_empty_pattern_table_times_out():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local index, captures, data = tio.expects({}, 100)
print("EMPTY_PATTERNS:" .. tostring(index == nil) .. ":" .. tostring(captures == nil) .. ":" .. tostring(data == ""))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.wait_stdout(b"EMPTY_PATTERNS:true:true:true")


def test_expects_invalid_pattern_raises_lua_error():
    script = """
tio.alwaysecho = false
tio.write("READY")
local go = tio.read(2, 1000)
local ok = pcall(tio.expects, {"OK", "%"}, 100)
print("BAD_PATTERN:" .. tostring(not ok))
tio.alwaysecho = true
"""
    with TioSession(script, ready=b"READY") as session:
        session.write_serial(b"GO")
        session.write_serial(b"x")
        session.wait_stdout(b"BAD_PATTERN:true")


EXPECT_TESTS = [
    test_expect_match,
    test_expect_capture_and_match_positions,
    test_expect_timeout_returns_received_data,
    test_expect_timeout_with_empty_data,
    test_expect_match_across_chunks,
    test_expect_match_with_preceding_and_trailing_data,
    test_expect_remaining_completes_pattern,
    test_expect_remaining_already_matches_without_new_input,
    test_expect_lua_pattern_and_capture,
    test_expect_invalid_pattern_raises_lua_error,
    test_expect_invalid_argument_types_raise_lua_error,
    test_expect_multiple_calls_with_remaining_buffer,
    test_expects_first_pattern_and_positions,
    test_expects_second_pattern_with_capture,
    test_expects_timeout_returns_received_data,
    test_expects_match_across_chunks,
    test_expects_earliest_completion_wins,
    test_expects_same_completion_uses_pattern_order,
    test_expects_accepts_single_pattern_string,
    test_expects_remaining_completes_pattern,
    test_expects_remaining_already_matches_without_new_input,
    test_expects_empty_pattern_table_times_out,
    test_expects_invalid_pattern_raises_lua_error,
]
