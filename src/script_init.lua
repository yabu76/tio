--
-- script_init file for tio
--
-- SPDX-License-Identifier: GPL-2.0-or-later
-- Copyright (c) 2014-2022  Martin Lund
--

table.unpack = table.unpack or unpack

tio.C = {
    EXPECT_READ_SIZE = 4096,
    WAIT_FOREVER = 0,
    NOWAIT = -1,
}

tio.reset_screen = function()
    io.write(string.format('%cc',0x1b))
end

tio.clear_screen = function()
    io.write(string.format('%c[H%c[2J', 0x1b, 0x1b))
end

tio.set = function(arg)
    local dtr = arg.DTR or -1
    local rts = arg.RTS or -1
    local cts = arg.CTS or -1
    local dsr = arg.DSR or -1
    local cd = arg.CD or -1
    local ri = arg.RI or -1
    tio.line_set(dtr, rts, cts, dsr, cd, ri)
end

tio.check_pattern = function(pattern)
    string.find("", pattern) -- invalid pattern raise exception.
end

tio.expect = function(pattern, timeout, remaining)
    local str = ''
    tio.check_pattern(pattern)
    while true do
        local astr
        if remaining then
            astr = remaining
            remaining = nil
        else
            astr = tio.read(tio.C.EXPECT_READ_SIZE, tio.C.NOWAIT)
        end
        local c = nil
        if not astr then
            c = tio.read(1, timeout)
            if not c then
                return nil, str
            end
        end
        str = table.concat{str, astr or '', c or ''}
        local captured = { string.find(str, pattern) }
        if captured[2] then
            local lpos = table.remove(captured, 1)
            local rpos = table.remove(captured, 1)
            if captured[1] then
                return table.unpack(captured), str, lpos, rpos
            else
                return str:sub(lpos, rpos), str, lpos, rpos
            end
        end
    end
end

tio.expects = function(patterns, timeout, remaining)
    str = ''
    if type(patterns) ~= 'table' then
        patterns = { patterns }
    end
    for _, pat in ipairs(patterns) do
        tio.check_pattern(pat)
    end
    while true do
        local astr
        if remaining then
            astr = remaining
            remaining = nil
        else
            astr = tio.read(tio.C.EXPECT_READ_SIZE, tio.C.NOWAIT)
        end
        local c = nil
        if not astr then
            c = tio.read(tio.C.EXPECT_READ_SIZE, timeout)
            if not c then
                return nil, nil, str
            end
        end
        str = table.concat{str, astr or '', c or ''}
        local found_1st = nil
        for idx, pat in ipairs(patterns) do
            local captured = { string.find(str, pat) }
            if captured[2] then
                local need_update = false
                if not found_1st then
                    found_1st = {}
                    need_update = true
                else
                    if captured[2] < found_1st.rpos then
                        need_update = true
                    end
                end
                if need_update then
                    found_1st.lpos = table.remove(captured, 1)
                    found_1st.rpos = table.remove(captured, 1)
                    found_1st.idx = idx
                    if captured[1] then
                        found_1st.captured = captured
                    else
                        found_1st.captured = {
                            str:sub(found_1st.lpos, found_1st.rpos)
                        }
                    end
                end
            end
        end
        if found_1st then
            return found_1st.idx, found_1st.captured, str, found_1st.lpos, found_1st.rpos
        end
    end
end

tio.subcmd_println = function(fmt, ...)
    tio.subcmd_puts(string.format(fmt, select(1, ...)))
end

tio.subcmd_warning_println = function(fmt, ...)
    tio.subcmd_warning_puts(string.format(fmt, select(1, ...)))
end

tio.subcmd_error_println = function(fmt, ...)
    tio.subcmd_error_puts(string.format(fmt, select(1, ...)))
end

tio.alwaysecho = true

setmetatable(tio, tio)
