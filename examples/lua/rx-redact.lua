-- Redact sensitive text from received serial output before tio displays,
-- logs, or forwards it to socket clients.
--
-- Usage:
--   tio --script-file examples/lua/rx-redact.lua /dev/ttyUSB0

tio.set_hook(tio.C.HK_IO_RECEIVE, function(data)
    data = data:gsub("password=[^%s]+", "password=<redacted>")
    data = data:gsub("token=[^%s]+", "token=<redacted>")

    return data
end)
