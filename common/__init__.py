# Copyright ⓒ 2016 Daniel Keep.
#
# Licensed under the MIT license (see LICENSE or <http://opensource.org
# /licenses/MIT>) or the Apache License, Version 2.0 (see LICENSE of
# <http://www.apache.org/licenses/LICENSE-2.0>), at your option. All
# files in the project carrying such notice may not be copied, modified,
# or distributed except according to those terms.

__all__ = [
    "RUSTUP",
    "USE_ANSI",
    "load_globals_from_metadata",
    "load_metadata_from_manifest",
    "msg",
    "msg_trace",
    "set_toolbox_trace",
    "sh",
    "sh_eval",
    "which",
]

import os
import os.path
import subprocess
import sys
import toml

from itertools import chain

TRACE = os.environ.get('TRACE_TOOLBOX', '') != ''
USE_ANSI = True if sys.platform != 'win32' else os.environ.get('FORCE_ANSI', '') != '' or os.environ.get('ConEmuANSI', 'OFF') == 'ON'

def which(programname, all=False):
    path_exts = os.environ.get('PATHEXT', '').split(os.path.pathsep)
    path_exts = [e for e in path_exts if e.lstrip() != '']

    def matches():
        for path in os.environ['PATH'].split(os.path.pathsep):
            base_path = os.path.join(path, programname)
            for ext in chain(('',), path_exts):
                ext_path = base_path+ext
                if os.path.exists(os.path.normcase(ext_path)):
                    yield ext_path

    if all:
        return matches()
    else:
        return next(matches(), None)

RUSTUP = "rustup" if which("rustup") is not None else "multirust"

def load_metadata_from_manifest(section):
    with open('Cargo.toml', 'rt') as manifest_file:
        manifest = toml.loads(manifest_file.read())
        return (manifest
            .get('package', {})
            .get('metadata', {})
            .get(section, {})
            )

def load_globals_from_metadata(section, globals, names):
    metadata = load_metadata_from_manifest(section)
    for (k, v) in metadata.items():
        k_ss = k.upper().replace('-', '_')
        if k_ss not in names:
            continue
        globals[k_ss] = v

def msg(*args):
    if USE_ANSI: sys.stdout.write('\x1b[1;34m')
    sys.stdout.write('> ')
    if USE_ANSI: sys.stdout.write('\x1b[1;32m')
    for arg in args:
        sys.stdout.write(str(arg))
    if USE_ANSI: sys.stdout.write('\x1b[0m')
    sys.stdout.write('\n')
    sys.stdout.flush()

def msg_trace(*args):
    if TRACE:
        if USE_ANSI: sys.stderr.write('\x1b[1;31m')
        sys.stderr.write('$ ')
        if USE_ANSI: sys.stderr.write('\x1b[0m')
        for arg in args:
            sys.stderr.write(str(arg))
        sys.stderr.write('\n')
        sys.stderr.flush()

def set_toolbox_trace(env_var):
    global TRACE
    TRACE = TRACE or os.environ.get(env_var, '') != ''

def sh(cmd, env=None, stdout=None, stderr=None, checked=True):
    msg_trace('sh(%r, env=%r)' % (cmd, env))
    try:
        subprocess.check_call(cmd, env=env, stdout=stdout, stderr=stderr, shell=True)
    except Exception as e:
        msg_trace('FAILED: %s' % e)
        if checked:
            raise
        else:
            return False
    if not checked:
        return True

def sh_eval(cmd, codec='utf-8', dont_strip=False):
    msg_trace('sh_eval(%r)' % cmd)
    result = None
    try:
        result = subprocess.check_output(cmd, shell=True).decode(codec)
        if not dont_strip:
            result = result.strip()
    except:
        msg_trace('FAILED!')
        raise
    return result
