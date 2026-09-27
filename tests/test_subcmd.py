#!/usr/bin/env python3

from _test_runner import TioSession


def test_subcmd_warning_println_formats_output():
    script = r'''
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    tio.subcmd_warning_println("warning %d", 42)
    return data
end)
'''

    with TioSession(script, mute=False) as session:
        session.write_serial(b"x")
        session.wait_stdout(b"warning 42")


def test_subcmd_error_println_accepts_formatted_arguments():
    script = r'''
tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    local ok, err = pcall(function()
        tio.subcmd_error_println("error %d", 42)
    end)

    if ok then
        tio.subcmd_println("ERROR_PRINTLN_OK")
    else
        tio.subcmd_println("ERROR_PRINTLN_FAILED:%s", err)
    end

    return data
end)
'''

    with TioSession(script, mute=False) as session:
        session.write_serial(b"x")
        session.wait_stdout(b"ERROR_PRINTLN_OK")


SUBCMD_TESTS = [
    test_subcmd_warning_println_formats_output,
    test_subcmd_error_println_accepts_formatted_arguments,
]
