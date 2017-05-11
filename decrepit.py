#!/usr/bin/env python3
# coding: utf-8

# Copyright ⓒ 2017 Daniel Keep.
#
# Licensed under the MIT license (see LICENSE or <http://opensource.org
# /licenses/MIT>) or the Apache License, Version 2.0 (see LICENSE of
# <http://www.apache.org/licenses/LICENSE-2.0>), at your option. All
# files in the project carrying such notice may not be copied, modified,
# or distributed except according to those terms.

"""
Usage: decrepit.py [-fv] [--distro=<NAME>]... [DATE]
       decrepit.py -a [-fRv] [--markdown | --json] [--distro=<NAME>]... [DATE]
       decrepit.py -l [-v] [DATE]

Determine the oldest supported version of Rust in the wild.  Sort of.  This
script scrapes public package repository information for the packaged version
of `rustc` in the (at time of last update) oldest, still-supported versions
of several Linux distributions.  It then reports the oldest `rustc` version
that you will need to support in order to support users of those
distributions.

Arguments:
  DATE      'As of' date: uses (potentially historical) data that is not more
            recent than this date, specified as 'YYYY-MM-DD'.

Options:
  -a, --all             Show all supported versions.
  -d, --distro=<NAME>   Check a specific distribution.  Use `name:release` to
                        specify a particular release.
  -f, --fast            Skip distros that are slow (>5 seconds) to check.
  -h, --help            Show help.
  -J, --json            Format output as JSON.
  -l, --list-distros    List known distros.
  -M, --markdown        Format table for Markdown.
  -R, --show-release    Show distribution releases.
  -v, --verbose         Show more information during operation.
  -V, --version         Show version.
"""

__author__ = "Daniel Keep"
__copyright__ = "Copyright 2017, Daniel Keep"
__license__ = "MIT"
__version__ = "0.1.8"
__requirements__ = """
docopt==0.6.2
lxml==3.7.3
tabulate==0.7.7
"""

# NOTE: used for comparisons, so don't avoid using it.
ROLLING = '(rolling)'

PROFILES = [
    {
        'date': '2017-04-14',
        'releases': {
            'arch': ROLLING,
            'debian': 'jessie',
            'debian-testing': 'stretch',
            'debian-unstable': 'sid',
            'fedora': '24',
            'fedora-latest': '25',
            'freebsd': '2017Q1',
            'freebsd-latest': '2017Q2',
            'nixos': ROLLING,
            'openbsd': '6.0',
            'openbsd-latest': '6.1',
            'opensuse': '42.2',
            'ubuntu': 'xenial',
            'ubuntu-latest': 'zesty',
        },
    },
    {
        'date': '2017-03-16',
        'releases': {
            'arch': ROLLING,
            'debian': 'jessie',
            'debian-testing': 'stretch',
            'debian-unstable': 'sid',
            'fedora': '24',
            'fedora-latest': '25',
            'nixos': ROLLING,
            'opensuse': '42.2',
            'ubuntu': 'xenial',
            'ubuntu-latest': 'yakkety',
        },
    },
]

# Distros that take more than ~5 seconds
SLOW_DISTROS = {'nixos'}

# How to look up package versions for different distros.
DISTROS = {
    'arch': {
        'url': 'https://www.archlinux.org/packages/community/x86_64/rust/',
        'xpath': r'//h2/text()',
        're': r'rust \d+:(?P<version>\d+[.]\d+[.]\d+)',
    },
    'debian': {
        'url': 'https://packages.debian.org/{release}/rustc',
        'xpath': r'//h1/text()',
        're': r'rustc [(](?P<version>\d+[.]\d+[.]\d+)',
    },
    'debian-testing': 'debian',
    'debian-unstable': 'debian',
    'fedora': lambda source: get_fedora(source),
    'fedora-latest': 'fedora',
    'freebsd': lambda source: get_freebsd(source),
    'freebsd-latest': 'freebsd',
    'nixos': lambda source: get_nixos(source),
    'openbsd': lambda source: get_openbsd(source),
    'openbsd-latest': 'openbsd',
    'opensuse': {
        'url': 'https://build.opensuse.org/package/view_file/openSUSE:Leap:{release}/rust/rust.spec?expand=1',
        'xpath': r'//pre/text()',
        're': r'Version:\s+(?P<version>\d+[.]\d+[.]\d+)',
    },
    'ubuntu': {
        'url': 'http://packages.ubuntu.com/{release}/rustc',
        'inherit': 'debian',
    },
    'ubuntu-latest': 'ubuntu',
}


import datetime
import docopt
import gzip
import json
import lxml.html
import os.path
import re
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from tabulate import tabulate


RE_VER = re.compile(r'(?P<ma>\d+)[.](?P<mi>\d+)([.](?P<re>\d+))')
VERBOSE = False


def main(args):
    # Parse args.
    args = docopt.docopt(__doc__, argv=args[1:], version='decrepit '+__version__)
    set_verbose(args['--verbose'])
    trace('Arguments: %r' % args)

    as_of_date = parse_date(args['DATE'])
    distro_strs = args['--distro']
    fast_only = args['--fast']
    list_distros = args['--list-distros']
    show_all = args['--all']
    show_rel = args['--show-release']
    show_json = args['--json']
    
    if args['--markdown']:
        tablefmt = 'pipe'
        table_esc = lambda x: x.replace('<', '&lt;').replace('>', '&gt;')
    else:
        tablefmt = 'simple'
        table_esc = lambda x: x

    distros = set()
    for distro_str in distro_strs:
        distros.update({d.split(':')[0].strip() for d in distro_str.split(',')})
    distros = list(distros)

    if len(distros) == 0:
        distros = list(DISTROS.keys())

    trace('distros: %r' % distros)

    # Find the right profile
    profiles = sorted(
        (p for p in PROFILES if p['date'] <= as_of_date),
        key = lambda p: p['date'],
        reverse = True,
    )

    if len(profiles) == 0:
        print('error: provided date `%s` is too old: no data available.' % as_of_date)
        return 1

    profile = profiles[0]
    trace('Profile: %r' % profile)

    # Allow overriding of distro args
    releases = profile['releases'].copy()
    for distro_str in distro_strs:
        releases.update({
            d:a
            for (d, a)
            in ((d.split(':', 1) + [''])[:2]
                for d
                in distro_str.split(','))
            if a.strip() is not ''
        })
    trace('releases: %r' % releases)

    # List distros?
    if list_distros:
        trace('known distros: ', newline=False)
        distros = (
            d + (':'+a if a != ROLLING else '')
            for (d, a)
            in sorted(releases.items(), key = lambda da: da[1])
        )
        print(', '.join(distros))
        return 0

    # Resolve the package versions
    def check(distro):
        if fast_only and distro in SLOW_DISTROS:
            return False
        return distro in distros

    def dispatch(da):
        distro, arg = da
        start_at = datetime.datetime.now()
        v = get_dispatch(distro, arg)
        secs = (datetime.datetime.now() - start_at).total_seconds()
        trace('get_dispatch(%r, %r): took %r seconds' % (distro, arg, secs))
        return (distro, v)

    trace('getting package versions...')
    start_at = datetime.datetime.now()
    pkg_vers = list(ThreadPoolExecutor().map(
        dispatch,
        (da for da in releases.items() if check(da[0]))
    ))
    took_secs = (datetime.datetime.now() - start_at).total_seconds()
    trace('took %r seconds overall' % took_secs)
    trace('pkg_vers: %r' % pkg_vers)

    pkg_vers = [
        (d, fmt_ver(v))
        for (d, v)
        in sorted(pkg_vers, key = lambda dv: (dv[1], dv[0]))
    ]

    if len(pkg_vers) == 0:
        print('error: no packages found!')
        return 2

    # Output.
    if show_all:
        if not show_rel:
            table_headers=['Distro', 'Version']
        else:
            pkg_vers = [(d, releases[d], v) for (d, v) in pkg_vers]
            table_headers=['Distro', 'Release', 'Version']

        if show_json:
            pkg_vers = [
                {h.lower(): f for (f, h) in zip(pkg_ver, table_headers)}
                for pkg_ver
                in pkg_vers
            ]
            print(json.dumps(pkg_vers, sort_keys=True))

        else:
            pkg_vers = [tuple(table_esc(f) for f in fs) for fs in pkg_vers]
            print(tabulate(pkg_vers, headers=table_headers, tablefmt=tablefmt))

    else:
        vs = [v for (_, v) in pkg_vers if v != '0.0.0'] + ['unknown']
        print(vs[0])


def set_verbose(value):
    global VERBOSE
    VERBOSE = value


def fmt_ver(ver):
    return '%d.%d.%d' % ver


def parse_date(date):
    """Should *probably* be "normalise", but oh well."""
    if date is None:
        date = datetime.datetime.now().date()
    else:
        date = datetime.date(*[
            int(p, 10) for p in
            chain(date.split('-')[:3], ['01']*2)
        ][:3])

    return '%04d-%02d-%02d' % (date.year, date.month, date.day)


def parse_semver(ver):
    m = RE_VER.match(ver)
    return tuple(int(m.group(g)) for g in ('ma', 'mi', 're'))


def get_dispatch(distro, arg):
    """
    Dispatch to the appropriate scraping function for the given distro.
    """
    defin = DISTROS[distro]
    try:
        if isinstance(defin, type(lambda:None)):
            return defin(arg)
        elif isinstance(defin, type("")):
            return get_dispatch(defin, arg)
        else:
            return get_scrape(distro, defin, arg)
    except:
        ex_ty, ex_ob, ex_tb = sys.exc_info()
        trace('get_dispatch(%r, %r) failed:' % (distro, arg))
        if VERBOSE:
            import traceback
            traceback.print_tb(ex_tb)
        trace('  %s: %s' % (ex_ty.__name__, ex_ob))
        return parse_semver('0.0.0')


def get_fedora(source):
    """
    Get package version by grabbing and parsing package metadata.
    """
    trace('get_fedora(%r)' % source)
    URL = ('https://apps.fedoraproject.org/packages/fcomm_connector'
           + '/bodhi/query/query_active_releases/'
           + '%7B%22filters%22:%7B%22package%22:%22rust%22%7D,'
           + '%22rows_per_page%22:100%7D')
    response = json.loads(urlopen(URL).read().decode('utf-8'))
    releases = response.get('rows', [])
    releases = [r for r in releases if source in r.get('release', None)]
    if len(releases) == 0:
        raise Exception("could not find package information for Fedora %s" % source)
    release = releases[0]

    re_ver = re.compile(r'>(\d+[.]\d+[.]\d+)(-[^<]+)?<')
    ver = release['stable_version']
    ver = re_ver.search(ver).group(1)
    return parse_semver(ver)


def get_freebsd(source):
    """
    Get package version by scraping a svnweb interface.
    """
    trace('get_freebsd(%r)' % source)
    params = {
        'svnweb': 'https://svnweb.freebsd.org/',
        'pkg': 'lang/rust',
    }
    pkg_url = '{svnweb}ports/branches/{rel}/{pkg}'.format(rel=source, **params)
    makefile_rev_xp = "//tr[td[1]/a/text()='\nMakefile']/td[2]//strong/text()"

    pkg_page = lxml.html.fromstring(urlopen(pkg_url).read())
    makefile_rev_res = pkg_page.xpath(makefile_rev_xp)[0]
    rev = ''.join(str(makefile_rev_res))

    makefile_url = '{svnweb}ports/branches/{rel}/{pkg}/Makefile?revision={rev}&view=co'.format(rel=source, rev=rev, **params)
    makefile_page = urlopen(makefile_url).read().decode('utf-8')
    re_ver = re.compile(r'(?m)^PORTVERSION[?]\s*=\s*(\d+[.]\d+[.]\d+)')
    ver = re_ver.search(makefile_page).group(1)
    return parse_semver(ver)


def get_openbsd(source):
    """
    Get package version by scraping a cvsweb interface.
    """
    trace('get_openbsd(%r)' % source)
    params = {
        'cvsweb': 'http://cvsweb.openbsd.org/cgi-bin/cvsweb/',
        'pkg': 'lang/rust',
        'release_tag': 'OPENBSD_{release_under}',
    }
    tag = params['release_tag'].format(release_under=source.replace('.', '_'))
    pkg_url = '{cvsweb}ports/{pkg}/?only_with_tag={tag}'.format(tag=tag, **params)
    makefile_rev_xp = r"//tr[td[1]/a[3]/text()='Makefile']/td[2]/a/b/text()"

    pkg_page = lxml.html.fromstring(urlopen(pkg_url).read())
    makefile_rev_res = pkg_page.xpath(makefile_rev_xp)[0]
    rev = ''.join(str(makefile_rev_res))

    makefile_url = '{cvsweb}~checkout~/ports/{pkg}/Makefile?rev={rev}&only_with_tag={tag}'.format(tag=tag, rev=rev, **params)
    makefile_page = urlopen(makefile_url).read().decode('utf-8')
    re_ver = re.compile(r'(?m)^V\s*=\s*(\d+[.]\d+[.]\d+)')
    ver = re_ver.search(makefile_page).group(1)
    return parse_semver(ver)


def get_nixos(source):
    """
    Get package version by grabbing and parsing the Nix package metadata.
    """
    trace('get_nixos(%r)' % source)
    assert source == ROLLING, "NixOS is a rolling-only release"
    URL = 'http://nixos.org/nixpkgs/packages.json.gz'

    # We try to cache the metadata because if we *don't*, then successive invocations can take many seconds and that's kinda bluh.
    trace('.. checking etag')
    last_etag = None
    tempdir = tempfile.gettempdir()
    if tempdir is not None:
        etag_path = os.path.join(tempdir, 'decrepit-nixos-packages.json.gz.etag')
        bs_gz_path = os.path.join(tempdir, 'decrepit-nixos-packages.json.gz')
        try:
            last_etag = open(etag_path, 'rb').read().decode('utf-8').strip()
        except:
            pass

    trace('.. last_etag: %r' % last_etag)

    req = urlopen(URL)
    cur_etag = req.getheader('etag')
    trace('.. cur_etag:  %r' % cur_etag)
    json_bs_gz = None
    if cur_etag == last_etag:
        trace('.. using cached package data')
        try:
            json_bs_gz = open(bs_gz_path, 'rb').read()
        except:
            pass

    if json_bs_gz is None:
        trace('.. redownloading package data')
        json_bs_gz = req.read()
        if tempdir is not None:
            trace('.. caching package data')
            open(etag_path, 'wb').write(cur_etag.encode('utf-8'))
            open(bs_gz_path, 'wb').write(json_bs_gz)

    json_bs = gzip.decompress(json_bs_gz)
    pkgs = json.loads(json_bs.decode('utf-8'))
    name = pkgs['packages']['rustc']['name']

    re_ver = re.compile(r'rustc-(\d+[.]\d+[.]\d+)')
    ver = re_ver.search(name).group(1)
    return parse_semver(ver)


def get_scrape(distro, defin, source):
    """
    Get package version by doing generic HTML scraping.

    Grabs a URL and evaluates a single XPath expression on it.
    """
    trace('get_scrape(%r, DISTROS[%r], %r)' % (distro, distro, source))
    if source is None:
        source = dict()
    if isinstance(source, str):
        source = {'release': source}

    if not isinstance(source, dict):
        raise Exception("expected source to be dict, got: %r" % source)

    while 'inherit' in defin:
        inherit = defin['inherit']
        new_defin = DISTROS[inherit].copy()
        new_defin.update({k:v for k,v in defin.items() if k != 'inherit'})
        defin = new_defin

    url = defin['url'].format(**source)
    xpath = defin['xpath'].format(**source)
    regex = re.compile(defin['re'])

    page = lxml.html.fromstring(urlopen(url).read())
    res = page.xpath(xpath)[0]
    text = ''.join(str(res))
    m = regex.search(text)
    if m is not None:
        version = m.group('version') or '0.0.0'
    else:
        version = '0.0.0'
    return parse_semver(version)


def urlopen(url):
    trace('urlopen(%r)' % url)
    return urllib.request.urlopen(url)


def trace(s, newline=True):
    if VERBOSE:
        sys.stderr.write(s + ('\n' if newline else ''))
        sys.stderr.flush()


if __name__ == '__main__':
    import sys
    if 'idlelib' not in sys.modules:
        r = main(sys.argv)
        if r is not None and r != 0:
            sys.exit(r)
