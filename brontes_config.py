from base_funcs import InhibitorError
import os

snapshot_db = {
    'brontes3d':{
        'repo_type':'git',
        'src':      'git://lex-bs.mmm.com/portage-overlay.git',
        'type':     'overlay'
    },
    'portage-cydonian':{
        'repo_type':'git',
        'src':      'git://lex-bs.mmm.com/portage-cydonian.git',
        'type':     'portage'
    }
}
 

# self.base[]
def base(**keywords):
    return {
        'debug':    True,
        'verbose':  True,
        'catalyst_support': True,
        'rootdir':  '/var/tmp/inhibitor/',
        'installdir':   os.getcwd()
    }
   
# self.X[]
def snapshot(**keywords):
    return snapshot_db[keywords['name']]

def stage(system_type='', stage='', **keywords):
    if 'cmdline' in keywords:
        for setting in keywords['cmdline'].split():
            name,value = setting.split('=')
            if name == 'system_type':
                system_type = value

    ret = {
        'snapshot':     ('portage-cydonian', 'd294453'),
        'overlays':     [ ('brontes3d', 'brontes-restorative-2.0.1_rc3') ],
        'profile':      'default/linux/amd64/2008.0/no-multilib',
        'portage_conf': get_portage_conf(stage),
        'make_conf':    get_make_conf(system_type),
        'arch':         'amd64',
        'seed':         'stage3-amd64-2009.01.09',
    }
# Left over
#   target stage
#   version_stamp
#   pre_fs_overlay, post_fs_overlay     (These shoudl just be scripts to run)
    return ret

def get_make_conf(system_type):
    if system_type == 'amd64':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    elif system_type == 'core2':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    else:
        raise InhibitorError("Unknown system_type:  '%s'" % system_type)

    return """
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
# vim: ft=sh
    """ % _cflags

def get_portage_conf(stage):
    portage_conf = {}
    if stage in ['stage1', 'stage2', 'stage3']:
        portage_conf['keywords.base'] = """
=sys-fs/udev-135*
=sys-apps/sysvinit-2.86*
=sys-apps/hal-0.5.11*
=sys-fs/cryptsetup-1.0.6*
=sys-apps/portage-2.1.6*
"""
    return portage_conf 
