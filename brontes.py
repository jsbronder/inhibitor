import inhibitor
import util
from actions import CreateSnapshotAction
from source import InhibitorSource
from actions import InhibitorStage



def get_make_conf(conf):
    if conf['system_type'] == 'amd64':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    elif conf['system_type'] == 'core2':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    else:
        raise InhibitorError("Unknown system_type:  '%s'" % system_type)

    return {'make.conf': """
        export GENTOO_MIRRORS="http://mirror.mmm.com/ http://gentoo.osuosl.org/ http://distfiles.gentoo.org/"
        export SYNC="rsync://lex-bs.mmm.com/portage-cydonian"
        export LINGUAS="en"
        export CHOST="x86_64-pc-linux-gnu"
        export MAKEOPTS="-j5"
        export VIDEO_CARDS="vesa"
        export EPAUSE_IGNORE=0
        export EBEEP_IGNORE=0
        export USE_ORDER="pkg:env:pkginternal:conf:defaults:env.d"
        export FEATURES="nodoc noinfo noman prefetch"
        export EMERGE_DEFAULT_OPTS="--jobs --load-average=8"

        export CFLAGS="%s"
        export CXXFLAGS="${CFLAGS}"
        # TODO: With gcc-4.3
        #export CFLAGS="-O2 -march=core2 -msse4_1 -pipe -fomit-frame-pointer"
        # vim: ft=sh""" % _cflags
    }




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
    seed            = 'stage3-amd64-cydonian-early-openrc-core2-r1'
)


def main():
    util.INHIBITOR_DEBUG = True
    i = inhibitor.Inhibitor()
    s = InhibitorStage(stageconf, 'cydonian')
    i.add_action(s)
    i.run()

if __name__ == '__main__':
    main()
