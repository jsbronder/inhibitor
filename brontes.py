import inhibitor
import util
from actions import CreateSnapshotAction
from source import (InhibitorSource, InhibitorScript)
from actions import InhibitorStage4



def get_make_conf(conf):
    if conf['system_type'] == 'amd64':
        _cflags = '-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    elif conf['system_type'] == 'core2':
        _cflags = '-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    else:
        raise util.InhibitorError("Unknown system_type:  '%s'" % conf['system_type'])

    return """
        GENTOO_MIRRORS="http://mirror.mmm.com/ http://gentoo.osuosl.org/ http://distfiles.gentoo.org/"
        SYNC="rsync://lex-bs.mmm.com/portage-cydonian"
        LINGUAS="en"
        CHOST="x86_64-pc-linux-gnu"
        MAKEOPTS="-j5"
        VIDEO_CARDS="vesa"
        EPAUSE_IGNORE=0
        EBEEP_IGNORE=0
        USE_ORDER="pkg:env:pkginternal:conf:defaults:env.d"
        FEATURES="nodoc noinfo noman prefetch parallel-fetch"
        EMERGE_DEFAULT_OPTS="--jobs --load-average=8"
        USE="-* bindist dlloader minimal no-old-linux nptl nptlonly xorg"

        CFLAGS="%s"
        CXXFLAGS="${CFLAGS}"
        # TODO: With gcc-4.3
        #CFLAGS="-O2 -march=core2 -msse4_1 -pipe -fomit-frame-pointer"
        # vim: ft=sh""" % _cflags

def package_list():
    return """
        sys-kernel/brontes-sources
        app-admin/pwgen
        app-admin/sudo
        app-admin/syslog-ng
        net-misc/dhcpcd
        net-misc/ntp
        sci-biology/brontes-restorative
        sys-apps/lava-cos-system
        sys-boot/grub-static
        sys-fs/device-mapper
        sys-fs/jfsutils
        sys-process/vixie-cron
        x11-base/xorg-x11
        x11-misc/touchcal
        x11-misc/imgscreensaver
        sys-apps/kexec-tools
        sys-power/acpid
        sys-fs/lvm2
        sys-apps/openrc
        sys-devel/bc
        sys-apps/less
        app-misc/screen
        media-gfx/splashutils
    """.split(' \n\t')

def test_script(args):
    return """
        #!/bin/bash
        echo "in Test script"
        echo
        env
        echo $1
        echo $2
        echo $3
        exit 0
    """

stageconf = util.Container(
    name            = 'cydonian',
    snapshot        = InhibitorSource(
        'git://lex-bs.mmm.com/portage-cydonian',
        rev='restorative-2.0.3_p4'),
    overlays        = [
        InhibitorSource(
            'git://lex-bs.mmm.com/portage-overlay',
            rev='restorative-2.0.3_p5')],
    profile         = 'default/linux/amd64/2008.0/no-multilib',
    portage_conf    = InhibitorSource(
        'file:///home/jbronder/scm/inhibitor/trunk/overlays/cydonian/etc-portage'),
    make_conf       = InhibitorSource(get_make_conf, system_type='core2'),
    arch            = 'amd64',
    seed            = 'stage3-amd64-cydonian-early-openrc-core2-r1',
    package_list    = package_list,
    scripts         = [InhibitorScript('test_script', test_script,
        args=['one arg', '--somestuff="blah"', 'more'])],
    kernel          = util.Container(
        kernel_pkg  = '=sys-kernel/brontes-sources-2.6.32',
        kconfig     = 'kconfig-2.6.32',
        gk_args     = '--splash=Brontes',
        packages    = 'x11-drivers/nvidia-drivers media-gfx/splash-themes-brontes'
    )
)


def main():
    util.INHIBITOR_DEBUG = True
    i = inhibitor.Inhibitor()
    s = InhibitorStage4(stageconf, 'cydonian')
    i.add_action(s)
    i.run()

if __name__ == '__main__':
    main()
