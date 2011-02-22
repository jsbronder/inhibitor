import sys
import os
import inhibitor

mydir = os.path.realpath(os.path.dirname(sys.argv[0]))

def get_make_conf(system_version='0.0', **keywds):
    return """
        LINGUAS="en"
        CHOST="i686-pc-linux-gnu"
        MAKEOPTS="-j5"
        VIDEO_CARDS="vesa"
        USE_ORDER="pkg:env:pkginternal:conf:defaults:env.d"
        FEATURES="nodoc noinfo noman parallel-fetch"
        EMERGE_DEFAULT_OPTS="--jobs --load-average=8"
        USE="bash-completion vim-syntax caps xcb"
        ACCEPT_LICENS="*"

        CFLAGS="-march=prescott -O2 -pipe -msse4.1"
        CXXFLAGS="${CFLAGS}"
        FCFLAGS="${CFLAGS}"
        FFFLAGS="${CFLAGS}"
        F77FLAGS="${CFLAGS}"
        LDFLAGS="${LDFLAGS} -Wl,--hash-style=gnu"
        
        # System Version %s
    """ % (system_version,)

def package_list():
    return """
        app-admin/sudo
        app-admin/syslog-ng
        net-misc/dhcpcd
        net-misc/ntp
        sys-process/vixie-cron
        app-misc/screen
        app-editors/vim
    """

stageconf = inhibitor.Container(
    name            = 'example',
    snapshot        = inhibitor.create_source('file:///var/tmp/portage',),
    profile         = 'default/linux/x86/10.0',
    make_conf       = inhibitor.create_source(get_make_conf, system_version='1.0'),
    arch            = 'x86',
    seed            = 'stage3-x86',
    packages        = package_list(),
    scripts         = [
        inhibitor.InhibitorScript('example_script', 'file:///%s' % os.path.join(mydir, 'example_script.sh'),
            args=['--system_version', '1.0'],
            needs=inhibitor.create_source('file:///%s' % os.path.join(mydir, 'needed.ex')) ),
        ],
)

def main():
    top_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[0]))),
        'sh')
    resume = True
    if '-f' in sys.argv:
        resume = False
    i = inhibitor.Inhibitor(paths={'share':top_dir})
    s = inhibitor.Stage4(stageconf, 'example', resume=resume)
    i.add_action(s)
    i.run()

if __name__ == '__main__':
    main()

