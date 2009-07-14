from base_funcs import InhibitorError

snapshot_db = {
    'brontes3d':{
        'type': 'git',
        'src':  'git://lex-bs.mmm.com/portage-overlay.git'
    },
    'portage-cydonian':{
        'type': 'git',
        'src':  'git://lex-bs.mmm.com/portage-cydonian.git'
    }
}
 

# self.base[]
def base(**keywords):
    return {
        'debug':    True,
        'verbose':  True,
        'catalyst_support': True,
        'rootdir':  '/var/tmp/inhibitor/',
    }
   
# self.X[]
def snapshot(**keywords):
    return snapshot_db[keywords['name']]

# self.build[]
def build_config(**keywords):
    # Need build_name
    # need base_name ? (caches)
    return {
        'snapshot':     ('portage-cydonian', 'revision'),
        'overlays':     [ ('brontes3d', 'revision') ],
        'profile':      'default/linux/amd64/2008.0/no-multilib',
        'portage_conf': {},
        'catalyst_env': "",
#Potentially necessary
        'arch':         ''
    }
# Left over
#   source_subpath
#   target stage
#   version_stamp
#   pre_fs_overlay, post_fs_overlay     (These shoudl just be scripts to run)


stage1_portage_conf = {
    'package.keywords/base':    """
# See build.
#=sys-apps/baselayout-2.0.0*
#=sys-apps/openrc-0.4.2*
=sys-fs/udev-135*
=sys-apps/sysvinit-2.86*
=sys-apps/hal-0.5.11*
=sys-fs/cryptsetup-1.0.6*

=sys-apps/portage-2.1.6*
"""
}


def stage1(s):
    get_stage_settings('stage1', s)



def get_stage_settings(stage, s):
    s[stage] = {}
    s[stage]['catalyst_env'] = get_catalyst_env(s['system_type'])
    s[stage]['portage_conf'] = get_portage_conf(stage)
    s[stage]['portage'] = ('portage-cydonian', 'd294453')

    if stage == 'stage4':
        s[stage]['overlays'] = [ ('brontes3d', 'c385a8') ]
        



def get_catalyst_env(system_type):
    if system_type == 'amd64':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    elif system_type == 'core2':
        _cflags='-O2 -march=athlon64 -pipe -fomit-frame-pointer'
    else:
        raise InhibitorException("Unknown system_type=='%s'" % settings['system_type'])

    catalyst_env = """
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

    return catalyst_env

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


        



build_settings = {
    'snapshots':{
        'portage-cydonian':{
            'rev':  'HEAD',
            'dest': '/usr/portage'
        }
    },

    'stage1': {
        'seed': 'stage3-amd64-2009.01.09'
    }
}