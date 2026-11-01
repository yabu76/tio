--
-- script_init file for tio
--
-- SPDX-License-Identifier: GPL-2.0-or-later
-- Copyright (c) 2014-2022  Martin Lund
--

table.unpack = table.unpack or unpack

tio.C = {
    EXPECT_CLEANUP_READ_SIZE = 4096,
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

tio.expect = function(pattern, timeout)
    local str = ''
    while true do
        local astr = tio.read(tio.C.EXPECT_CLEANUP_READ_SIZE, tio.C.NOWAIT)
        local c = nil
        if astr == nil then
            c = tio.read(1, timeout)
            if c == nil then
                return nil, str
            end
        end
        str = table.concat{str, astr or '', c or ''}
        local captured = { string.match(str, pattern) }
        if #captured > 0 then
            return table.unpack(captured), str
        end
    end
end

tio.expects = function(patterns, timeout)
    local str = ''
    if type(patterns) ~= 'table' then
        patterns = { patterns }
    end
    while true do
        local astr = tio.read(tio.C.EXPECT_CLEANUP_READ_SIZE, tio.C.NOWAIT)
        local c = nil
        if astr == nil then
            c = tio.read(1, timeout)
            if c == nil then
                return nil, nil, str
            end
        end
        str = table.concat{str, astr or '', c or ''}
        for idx, pat in ipairs(patterns) do
            local captured = { string.match(str, pat) }
            if #captured > 0 then
                return idx, captured, str
            end
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

