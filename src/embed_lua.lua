#!/usr/bin/env lua

-- SPDX-License-Identifier: GPL-2.0-or-later

src = arg[1]
dst = arg[2]

local fh_src = io.open(src, "rb")
local fh_dst = io.open(dst, "wb")

if not fh_src then
    error(string.format("source file not found. : %s", src))
end

if not fh_dst then
    error(string.format("destination file cannot open. : %s", dst))
end

fh_dst:write("/* Generated file. Do not edit. */\n")
fh_dst:write("static const char script_init[] = {\n")

while true do
    local chunk = fh_src:read(16)
    if not chunk or #chunk == 0 then
        break
    end
    fh_dst:write("    ")
    for idx = 1, #chunk do
        local hex = string.format("0x%02x,", chunk:byte(idx))
        fh_dst:write(hex)
    end
    fh_dst:write("\n")
end

fh_dst:write("    0x00\n")
fh_dst:write("};\n")

fh_dst:close()
fh_src:close()

os.exit(0)
