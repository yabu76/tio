# Generate version header
version_h = vcs_tag(command : ['git', 'describe', '--tags', '--always', '--dirty'],
                        input : 'version.h.in',
                        output :'version.h',
                        replace_string:'@VERSION@')

config_h = configuration_data()
config_h.set('BAUDRATE_CASES', baudrate_cases)
configure_file(output: 'config.h', configuration: config_h)

tio_sources = [
  'error.c',
  'log.c',
  'main.c',
  'options.c',
  'misc.c',
  'tty.c',
  'print.c',
  'configfile.c',
  'signals.c',
  'socket.c',
  'setspeed.c',
  'rs485.c',
  'timestamp.c',
  'alert.c',
  'xymodem.c',
  'script.c',
  'fs.c',
  'readline.c',
  version_h
]

tio_dep = [
  dependency('threads', required: true),
  dependency('glib-2.0', required: true),
]

use_luajit = get_option('use_luajit')
if use_luajit
  foreach name: ['luajit', 'luajit-5.1']
    luajit_dep = dependency(name, version: '>=2.1', required: false)
    if luajit_dep.found()
      break
    endif
  endforeach
endif
if not (use_luajit and luajit_dep.found())
  foreach name: ['lua-5.4', 'lua-5.3', 'lua-5.2', 'lua-5.1', 'lua']
    lua_dep = dependency(name, version: '>=5.1', required: false)
    if lua_dep.found()
      break
    endif
  endforeach
endif
if use_luajit and luajit_dep.found()
  tio_dep += [luajit_dep]
elif lua_dep.found()
  tio_dep += [lua_dep]
else
  error('Lua could not be found!')
endif

if host_machine.system() == 'darwin'
  iokit_dep = dependency('appleframeworks', modules: ['IOKit'], required: true)
  corefoundation_dep = dependency('appleframeworks', modules: ['CoreFoundation'], required: true)
  tio_dep += [iokit_dep, corefoundation_dep]
endif

if host_machine.system() == 'haiku'
  network_dep = meson.get_compiler('c').find_library('network', required:true)
  tio_dep += [network_dep]
endif

tio_c_args = ['-Wshadow','-Wno-unused-result']

if enable_setspeed2
  tio_c_args += '-DHAVE_TERMIOS2'
endif

if enable_iossiospeed
  tio_c_args += '-DHAVE_IOSSIOSPEED'
endif

if enable_rs485
  tio_c_args += '-DHAVE_RS485'
endif

tio_exe = executable('tio',
  tio_sources,
  c_args: tio_c_args,
  dependencies: tio_dep,
  install: true )

python3 = find_program('python3', required: false)
if python3.found()
  test('rx-filter', python3,
    args: [files('../tests/rx_filter.py'), tio_exe],
    timeout: 30)
endif

subdir('bash-completion')
