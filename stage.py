import os
import util
import glob
import re

import actions
import source

def make_conf_source(**keywds):
    ex_vars     = {}
    src         = None
    make_conf   = {}

    if 'ex_vars' in keywds:
        ex_vars = keywds['ex_vars']

    if 'source' in keywds:
        src = keywds['source']

    if src:
        make_conf = util.make_conf_dict(src)

    for k in ex_vars:
        if not k in make_conf.keys():
            make_conf[k] = ex_vars[k]
        else:
            for v in ex_vars[k].split(' '):
                if not v in make_conf[k]:
                    make_conf[k] += ' ' + v
    ret = ""
    for k, v in ex_vars:
        ret += '%s="%s"\n' % (k, v)
    return ret


class BaseStage(actions.InhibitorAction):
    def __init__(self, stage_conf, build_name, stage_name='base_stage', **keywds):
        self.build_name     = '%s-%s' %  (stage_name, build_name)
        self.conf           = stage_conf
        self.sources        = []
        self.istate         = None
        self.target_root    = None
        self.profile        = None
        self.aux_mounts     = {}
        self.aux_sources    = {}

        self.root           = util.Path('/')
        self.portage_cr     = util.Path('/tmp/inhibitor/portage_configroot')

        if 'root' in keywds:
            self.root       = keywds['root']
        if 'portage_cr' in keywds:
            self.portage_cr = keywds['portage_cr']

        self.env            = {
            'PKGDIR':                   '/tmp/inhibitor/pkgs',
            'DISTDIR':                  '/tmp/inhibitor/dist',
            'INHIBITOR_SCRIPT_ROOT':    '/tmp/inhibitor/sh',
            'ROOT':                     self.root,
            'PORTAGE_CONFIGROOT':       self.portage_cr,
            'PORTDIR_OVERLAY':          '',
            'PORTDIR':                  '/tmp/inhibitor/portdir'
        }
        super(BaseStage, self).__init__(self.build_name, **keywds)

    def post_conf(self, inhibitor_state):
        super(BaseStage, self).post_conf(inhibitor_state)

        self.target_root = self.istate.paths.build.pjoin(self.build_name)
        util.mkdir(self.target_root)

        self.aux_mounts = {
            'proc': util.Mount('/proc', '/proc', self.target_root),
            'sys':  util.Mount('/sys',  '/sys',  self.target_root),
            'dev':  util.Mount('/dev',  '/dev',  self.target_root),
        }
        self.aux_sources = {
            'resolve.conf': source.create_source(
                    'file://etc/resolv.conf', keep = True, dest = '/etc/resolv.conf'),
            'hosts':        source.create_source(
                    'file://etc/hosts', keep = True, dest = '/etc/hosts'),
        }
                    

        pkgcache = source.create_source(
            "file://%s" % util.mkdir(self.istate.paths.pkgs.pjoin(self.build_name)),
            keep = False,
            dest = self.env['PKGDIR']
        )
        self.sources.append(pkgcache)

        distcache = source.create_source(
            "file://%s" % util.mkdir(self.istate.paths.dist),
            keep = False,
            dest = self.env['DISTDIR']
        )
        self.sources.append(distcache)

        if self.conf.has('snapshot'):
            self.conf.snapshot.keep = False
            self.conf.snapshot.dest = util.Path( self.env['PORTDIR'] )
            self.sources.append(self.conf.snapshot)
        else:
            rc, portdir = util.cmd_out('portageq portdir', raise_exception=True)
            self.sources.append( 
                source.create_source( 'file://' + portdir,
                    keep = False,
                    dest = util.Path( self.env['PORTDIR'] ))
            )

        if self.conf.has('overlays'):
            i = 0
            for overlay in self.conf.overlays:
                overlay.keep = False
                overlay.dest = util.Path('/tmp/inhibitor/overlays/%d' % i)
                self.sources.append(overlay)
                self.env['PORTDIR_OVERLAY'] += ' /tmp/inhibitor/overlays/%d' % i
                i += 1

        for i in glob.iglob( self.istate.paths.share.pjoin('*.sh') ):
            j = source.create_source(
                    "file://%s" % i,
                    keep = False,
                    dest = self.env['INHIBITOR_SCRIPT_ROOT'] + '/' + os.path.basename(i)
                )
            self.sources.append(j)

        if self.conf.has('profile'):
            self.profile = self.conf.profile
        else:
            self.profile = os.readlink('/etc/make.profile')
            self.profile = re.sub('.*/profiles/', '', self.profile)

        if self.conf.has('make_conf'):
            mc = self.conf.make_conf
        else:
            mc = make_conf_source( source='/etc/make.conf')
        mc.dest = self.portage_cr.pjoin('etc/make.conf')
        mc.keep = True
        self.sources.append(mc)

        if self.conf.has('portage_conf'):
            self.conf.portage_conf.dest = self.portage_cr.pjoin('etc/portage')
            self.conf.portage_conf.keep = True
            self.sources.append(self.conf.portage_conf)

        for src in self.sources:
            src.post_conf( self.istate )
            src.init()

        for _, src in self.aux_sources.items():
            src.post_conf( self.istate )
            src.init()

    def install_sources(self):
        for src in self.sources:
            src.install( root = self.target_root )

    def make_profile_link(self):
        targ = self.target_root.pjoin(self.portage_cr + '/etc/make.profile')
        util.mkdir( os.path.dirname(targ) )
        if os.path.lexists(targ):
            os.unlink(targ)
            os.symlink('/usr/portage/profiles/%s' % self.conf.profile, targ)

    def remove_sources(self):
        for src in self.sources:
            src.remove()

    def clean_sources(self):
        for src in self.sources:
            src.finish()
        for _, src in self.aux_sources.items():
            if not src in self.sources:
                src.finish()

    def get_action_sequence(self):
        return [
            util.Step(self.install_sources,     always=True),
            util.Step(self.make_profile_link,   always=True),
            util.Step(self.remove_sources,      always=True),
            util.Step(self.clean_sources,       always=True)
        ]
    
