#!/usr/bin/env python3
# coding: utf-8

# Copyright ⓒ 2016 Daniel Keep.
#
# Licensed under the MIT license (see LICENSE or <http://opensource.org
# /licenses/MIT>) or the Apache License, Version 2.0 (see LICENSE of
# <http://www.apache.org/licenses/LICENSE-2.0>), at your option. All
# files in the project carrying such notice may not be copied, modified,
# or distributed except according to those terms.

import os.path
import re
import sys
import yaml

from common import *
from itertools import chain

LOG_DIR = os.path.join('local', 'tests')

set_toolbox_trace(env_var='TRACE_TEST_MATRIX')

def main():
    load_globals_from_metadata('test-matrix', globals(),
        {
            'LOG_DIR',
        })

    travis = yaml.load(open('.travis.yml'))
    script = translate_script(travis.get('script', None))
    default_rust_vers = travis['rust']

    matrix_includes = travis.get('matrix', {}).get('include', [])

    vers = set(default_rust_vers)
    include_vers = []
    exclude_vers = set()

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    for arg in sys.argv[1:]:
        if arg in vers and arg not in include_vers:
            include_vers.append(arg)
        elif arg.startswith('-') and arg[1:] in vers:
            exclude_vers.add(arg[1:])
        else:
            msg("Don't know how to deal with argument `%s`." % arg)
            sys.exit(1)

    if include_vers == []:
        include_vers = default_rust_vers[:]

    rust_vers = [v for v in include_vers if v not in exclude_vers]
    msg('Tests will be run for: %s' % ', '.join(rust_vers))

    results = []
    for rust_ver in rust_vers:
        seq_id = 0
        for env_var_str in travis.get('env', [""]):
            env_vars = parse_env_vars(env_var_str)
            for row in chain([{}], matrix_includes):
                if row.get('rust', None) not in (None, rust_ver):
                    continue

                row_env_vars = parse_env_vars(row.get('env', ""))

                cmd_env = {}
                cmd_env.update(env_vars)
                cmd_env.update(row_env_vars)

                success = run_script(script, rust_ver, seq_id, cmd_env)
                results.append((rust_ver, seq_id, success))
                seq_id += 1

    print("")

    msg('Results:')
    for rust_ver, seq_id, success in results:
        msg('%s #%d: %s' % (rust_ver, seq_id, 'OK' if success else 'Failed!'))

def parse_env_vars(s):
    env_vars = {}
    for m in re.finditer(r"""([A-Za-z0-9_]+)=(?:"([^"]+)"|(\S*))""", s.strip()):
        k = m.group(1)
        v = m.group(2) or m.group(3)
        env_vars[k] = v
    return env_vars

def run_script(script, rust_ver, seq_id, env):
    target_dir = os.path.join('target', '%s-%d' % (rust_ver, seq_id))
    log_path = os.path.join(LOG_DIR, '%s-%d.log' % (rust_ver, seq_id))
    log_file = open(log_path, 'wt')
    msg('Running tests for %s #%d...' % (rust_ver, seq_id))
    success = True

    def sub_env(m):
        name = m.group(1) or m.group(2)
        return cmd_env[name]

    log_file.write('# %s #%d\n' % (rust_ver, seq_id))
    for k, v in env.items():
        log_file.write('# %s=%r\n' % (k, v))

    cmd_env = os.environ.copy()
    cmd_env['CARGO_TARGET_DIR'] = target_dir
    cmd_env.update(env)

    for cmd in script:
        cmd = re.sub(r"\$(?:([A-Za-z0-9_]+)|{([A-Za-z0-9_]+)})\b", sub_env, cmd)
        cmd_str = '> %s run %s %s' % (RUSTUP, rust_ver, cmd)
        log_file.write(cmd_str)
        log_file.write("\n")
        log_file.flush()
        success = sh(
            '%s run %s %s' % (RUSTUP, rust_ver, cmd),
            checked=False,
            stdout=log_file, stderr=log_file,
            env=cmd_env,
            )
        if not success:
            log_file.write('Command failed.\n')
            log_file.flush()
            break
    msg('... ', 'OK' if success else 'Failed!')
    log_file.close()
    return success

def translate_script(script):
    script = script or "rustc -vV && cargo -vV && cargo build --verbose && cargo test --verbose"
    parts = script.split("&&")
    return [p.strip() for p in parts]

if __name__ == '__main__':
    main()
