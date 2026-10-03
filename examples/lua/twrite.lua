--
-- tio.twrite() uses output-mapping, output-delay and input-mode.
--
-- This script sends
--   Hello.
--   This is Hex mode.
--   This is Hex mode.
--   Bye.
--

tio.set_input_mode(tio.C.IM_NORMAL)
tio.twrite("Hello.\r\n")

tio.set_input_mode(tio.C.IM_HEX)
tio.twrite("5468697320697320486578206d6f64652e0d0a") -- "This is Hex mode."
tio.twrite("54 68 69 73 20 69 73 20 48 65 78 20 6d 6f 64 65 2e 0d 0a") -- "This is Hex mode."

tio.set_input_mode(tio.C.IM_LINE)
tio.twrite("Bye.\r\n")

tio.set_input_mode(tio.C.IM_NORMAL)

