import os
import util
import glob
import re
import shutil
import tarfile
import types

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
    """
    Basic stage building action.  Handles fetching sources and setting up the chroot
    to be able to merge packages.  Also cleans everything up afterwards.

    @param stage_conf       - Stage configuration, see below.
    @param build_name       - Unique string to identify the stage.
    @param stage_name       - Type of stage being built.  Default is base_stage.

    Stage Configuration:
        @param name         -
        @param seed         - Name of the seed stage to use for building.  Stage
                              needs to be located in inhibitor's stagedir.
        @param fs_sources   - List of InhibitorSources to be added to the stage.  The
                              sources are added during install_sources().  If
                              source.keep is set, the source will persist in the file
                              stage image, otherwise it is removed during
                              remove_sources().

    """
    def __init__(self, stage_conf, build_name, stage_name='base_stage', **keywds):
        self.build_name     = '%s-%s' %  (stage_name, build_name)
        self.conf           = stage_conf
        self.sources        = []
        self.istate         = None
        self.target_root    = None
        self.tarpath        = None
        self.seed           = None
        self.fs_sources     = None
        self.aux_mounts     = {}
        self.aux_sources    = {}
        self.root           = util.Path('/')

        self.env            = {
            'INHIBITOR_SCRIPT_ROOT':    '/tmp/inhibitor/sh',
            'ROOT':                     self.root,
        }

        if self.conf.has('seed'):
            self.seed = self.conf.seed
        else:
            raise util.InhibitorError('No seed stage specified')

        super(BaseStage, self).__init__(self.build_name, **keywds)

    def update_root(self, new_root):
        self.root = new_root
        self.env['ROOT'] = new_root

    def chroot_failure(self):
        util.umount_all(self.istate.mount_points)

    def post_conf_begin(self, inhibitor_state):
        super(BaseStage, self).post_conf(inhibitor_state)
        self.target_root    = self.istate.paths.build.pjoin(self.build_name)
        self.tarpath        = self.istate.paths.stages.pjoin(self.build_name + '.tar.bz2')
        util.mkdir(self.target_root)
        if self.seed:
            self.seed       = self.istate.paths.stages.pjoin(self.seed)

        self.aux_mounts = {
            'proc': util.Mount('/proc', '/proc', self.target_root),
            'sys':  util.Mount('/sys',  '/sys',  self.target_root),
            'dev':  util.Mount('/dev',  '/dev',  self.target_root),
            'devpts':   util.Mount('/dev/pts',  '/dev/pts', self.target_root),
        }
        self.aux_sources = {
            'resolv.conf': source.create_source(
                    'file://etc/resolv.conf', keep = True, dest = '/etc/resolv.conf'),
            'hosts':        source.create_source(
                    'file://etc/hosts', keep = True, dest = '/etc/hosts'),
        }

        for i in glob.iglob( self.istate.paths.share.pjoin('*.sh') ):
            j = source.create_source(
                    "file://%s" % i,
                    keep = False,
                    dest = self.env['INHIBITOR_SCRIPT_ROOT'] + '/' + os.path.basename(i)
                )
            self.sources.append(j)

        if self.conf.has('fs_sources'):
            if not type(self.conf.fs_sources) in (types.ListType, types.TupleType):
                self.conf.fs_sources = [self.conf.fs_sources]

            for src in self.conf.fs_sources:
                if not src.dest:
                    util.warn("Setting dest for %s to '/'" % (src.src,))
                    src.dest = util.Path('/')
                if src.mountable and src.dest == util.Path('/'):
                    util.warn("Setting mountable=False on %s" % (src.src,))
                    src.mountable = False
                self.sources.append(src)

    def post_conf_finish(self):
        for src in self.sources:
            src.post_conf( self.istate )
            src.init()

        for _, src in self.aux_sources.items():
            src.post_conf( self.istate )
            src.init()

    def post_conf(self, inhibitor_state, run_finish=True):
        self.post_conf_begin(inhibitor_state)
        if run_finish:
            self.post_conf_finish()

    def unpack_seed(self):
        if not os.path.isdir(self.seed):
            if os.path.exists(self.seed):
                os.unlink(self.seed)
            seedfile = self.seed + '.tar.bz2'
            util.info("Unpacking %s" % seedfile)
            os.makedirs(self.seed)
            try:
                util.cmd('tar -xjpf %s -C %s/' % (seedfile, self.seed))
            except:
                shutil.rmtree(self.seed)
                raise

        util.info("Syncing %s to %s" % (self.seed.dname(), self.target_root.dname()) )
        util.cmd('rsync -a --delete %s %s' %
            (self.seed.dname(), self.target_root.dname()) )

    def install_sources(self):
        for src in self.sources:
            src.install( root = self.target_root )

        for m in ('proc', 'sys', 'dev', 'devpts'):
            util.mount( self.aux_mounts[m], self.istate.mount_points )
        for m in ('resolv.conf', 'hosts'):
            self.aux_sources[m].install( root = self.target_root )

    def remove_sources(self):
        for src in [x for x in self.sources if (x.keep and not x.mountable)]:
            # Previous actions may have overwritten the source, so
            # it needs to be reinstalled one last time.
            src.install( root = self.target_root )

        for src in self.sources:
            src.remove()
        for m in ('proc', 'sys', 'devpts', 'dev'):
            util.umount( self.aux_mounts[m], self.istate.mount_points )
        for m in ('resolv.conf', 'hosts'):
            self.aux_sources[m].remove()

    def finish_sources(self):
        for src in self.sources:
            src.finish()
        for _, src in self.aux_sources.items():
            if not src in self.sources:
                src.finish()

    def clean_tmp(self):
        shutil.rmtree(self.target_root.pjoin('/tmp/inhibitor'))

    def get_action_sequence(self):
        return [
            util.Step(self.install_sources,     always=True),
            util.Step(self.remove_sources,      always=True),
            util.Step(self.finish_sources,      always=True),
            util.Step(self.clean_tmp,           always=True),
        ]

    def pack(self):
        archive = tarfile.open(self.tarpath, 'w:bz2')
        archive.add(self.target_root,
            arcname = '/',
            recursive = True,
        )
        archive.close()
        util.info("Created %s" % (self.tarpath,))


class BaseGentooStage(BaseStage):
    """
    Basic stage building action.  Handles fetching sources and setting up the chroot
    to be able to merge packages.  Also cleans everything up afterwards.

    @param stage_conf       - Stage configuration, see below.
    @param build_name       - Unique string to identify the stage.
    @param stage_name       - Type of stage being built.  Default is base_stage.

    Stage Configuration:
        @param name         -
        @param snapshot     - InhibitorSource representing the portage tree.
        @param overlays     - List of InhibitorSources' to use as portage overlays.
        @param kernel       - Container for kernel configuration.
            kernel_pkg      - String passed to emerge to get kernel package.
            kconfig         - InhibitorSource that contains the kernel config.
            genkernel       - Arguments to pass to genkernel when building the
                              initramfs.
            packages        - List of packages that should be installed after the
                              kernel has been configured.
        @param profile      - Portage profile to use.
        @param seed         - Name of the seed stage to use for building.  Stage
                              needs to be located in inhibitor's stagedir.
        @param make_conf    - InhibitorSource for make.conf.
        @param portage_conf - InhibitorSource with the contents for /etc/portage.

    """
    def __init__(self, stage_conf, build_name, stage_name='base_stage', **keywds):
        super(BaseGentooStage, self).__init__(stage_conf, build_name, stage_name=stage_name, **keywds)
        self.profile        = None
        self.kernel         = None
        self.pkgcache       = None

        self.portage_cr     = util.Path('/tmp/inhibitor/portage_configroot')
        self.env.update({
            'PKGDIR':                   '/tmp/inhibitor/pkgs',
            'DISTDIR':                  '/tmp/inhibitor/dist',
            'PORTAGE_CONFIGROOT':       self.portage_cr,
            'PORTDIR':                  '/tmp/inhibitor/portdir'
        })

        if self.conf.has('overlays'):
            self.env['PORTDIR_OVERLAY'] = ''

        if self.conf.has('pkgcache'):
            self.pkgcache = self.conf.pkgcache


    def update_portage_cr(self, new_portage_cr):
        self.portage_cr = new_portage_cr
        self.env['PORTAGE_CONFIGROOT'] = new_portage_cr

    def post_conf(self, inhibitor_state):
        super(BaseGentooStage, self).post_conf(inhibitor_state, run_finish=False)
        if not self.pkgcache:
            self.pkgcache = source.create_source(
                "file://%s" % util.mkdir(self.istate.paths.pkgs.pjoin(self.build_name)) )
        self.pkgcache.keep = False
        self.pkgcache.dest = self.env['PKGDIR']
        self.sources.append(self.pkgcache)

        distcache = source.create_source(
            "file://%s" % util.mkdir(self.istate.paths.dist),
            keep = False,
            dest = self.env['DISTDIR']
        )
        self.sources.append(distcache)

        if self.conf.has('kernel'):
            self.kernel = self.conf.kernel
            if not self.kernel.has('kconfig'):
                raise util.InhibitorError('No kernel config (kconfig) specified.')
            else:
                self.kernel.kconfig.keep = False
                self.kernel.kconfig.dest = util.Path('/tmp/inhibitor/kconfig')
                self.kernel.kconfig.post_conf(inhibitor_state)
                self.sources.append(self.kernel.kconfig)
            if not self.kernel.has('kernel_pkg'):
                raise util.InhibitorError('No kernel package (kernel_pkg) specified.')

            kerncache = source.create_source(
                "file://%s" % util.mkdir(inhibitor_state.paths.kernel.pjoin(self.build_name)),
                keep = False,
                dest = '/tmp/inhibitor/kerncache'
            )
            self.sources.append(kerncache)

        if self.conf.has('snapshot'):
            self.conf.snapshot.keep = False
            self.conf.snapshot.dest = util.Path( self.env['PORTDIR'] )
            self.sources.append(self.conf.snapshot)
        else:
            _, portdir = util.cmd_out('portageq portdir', raise_exception=True)
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

        if self.conf.has('profile'):
            self.profile = self.conf.profile
        else:
            self.profile = os.readlink('/etc/make.profile')
            self.profile = re.sub('.*/profiles/', '', self.profile)

        if self.conf.has('make_conf'):
            mc = self.conf.make_conf
        else:
            mc = source.create_source(make_conf_source, source='/etc/make.conf')
        mc.dest = self.portage_cr.pjoin('etc/make.conf')
        mc.keep = True
        self.sources.append(mc)

        if self.conf.has('portage_conf'):
            self.conf.portage_conf.dest = self.portage_cr.pjoin('etc/portage')
            self.conf.portage_conf.keep = True
            self.sources.append(self.conf.portage_conf)

        self.post_conf_finish()


    def make_profile_link(self):
        # XXX:  We also need to make the root profile link, Gentoo Bug 324179.
        for d in (self.target_root, self.target_root.pjoin(self.portage_cr)):
            targ = d.pjoin('/etc/make.profile')
            util.mkdir( os.path.dirname(targ) )
            if os.path.lexists(targ):
                os.unlink(targ)
            os.symlink(self.env['PORTDIR'] + '/profiles/%s' % self.profile, targ)

    def restore_profile_link(self):
        # XXX:  See make_profile_link.
        targ = self.target_root.pjoin('/etc/make.profile')
        if os.path.lexists(targ):
            os.unlink(targ)
        os.symlink('../usr/portage/profiles/%s' % self.profile, targ)

    def get_action_sequence(self):
        return [
            util.Step(self.install_sources,     always=True),
            util.Step(self.make_profile_link,   always=True),
            util.Step(self.remove_sources,      always=True),
            util.Step(self.finish_sources,      always=True),
            util.Step(self.restore_profile_link,always=True),
            util.Step(self.clean_tmp,           always=True),
        ]


class Stage4(BaseGentooStage):
    """
    Stage 4 building action.  Handles fetching sources, setting up the chroot,
    merging packages, configuring a kernel and running any specified scripts
    inside the completed build.

    @param stage_conf       - Stage configuration, see below.
    @param build_name       - Unique string to identify the stage.
    @param stage_name       - Type of stage being built.  Default is base_stage.

    Stage Configuration:
        @param name         -
        @param snapshot     - InhibitorSource representing the portage tree.
        @param overlays     - List of InhibitorSources' to use as portage overlays.
        @param kernel       - Container for kernel configuration.
            kernel_pkg      - String passed to emerge to get kernel package.
            kconfig         - InhibitorSource that contains the kernel config.
            genkernel       - Arguments to pass to genkernel when building the
                              initramfs.
            packages        - List of packages that should be installed after the
                              kernel has been configured.
        @param profile      - Portage profile to use.
        @param seed         - Name of the seed stage to use for building.  Stage
                              needs to be located in inhibitor's stagedir.
        @param make_conf    - InhibitorSource for make.conf.
        @param portage_conf - InhibitorSource with the contents for /etc/portage.

        @param scripts      - List of Scripts to run after merging all packages and
                              building the kernel.  They run in order inside of the
                              completed chroot from '/tmp/inhibitor/sh/'
        @param packages     - List or String of packages to merge.
    """
    def __init__(self, stage_conf, build_name, **keywds):
        self.package_list   = []
        self.scripts        = []

        super(Stage4, self).__init__(stage_conf, build_name, 'stage4', **keywds)
        self.emerge_cmd     = '%s/inhibitor-run.sh run_emerge ' % (self.env['INHIBITOR_SCRIPT_ROOT'],)

    def post_conf(self, inhibitor_state):
        super(Stage4, self).post_conf(inhibitor_state)

        if self.conf.has('scripts'):
            self.scripts = self.conf.scripts
            for script in self.conf.scripts:
                script.post_conf(inhibitor_state)

        if self.conf.has('packages'):
            self.package_list = util.strlist_to_list(self.conf.packages)
        else:
            raise util.InhibitorError('No packages specified')

    def _emerge(self, packages, flags=''):
        util.chroot(
            path = self.target_root,
            function = util.cmd,
            fargs = {
                'cmdline': '%s %s %s' % (
                    self.emerge_cmd,
                    flags,
                    packages
                ),
                'env': self.env
            },
            failuref = self.chroot_failure
        )

    def get_action_sequence(self):
        ret = []
        ret.append( util.Step(self.unpack_seed,             always=False)   )
        ret.append( util.Step(self.install_sources,         always=True)    )
        ret.append( util.Step(self.make_profile_link,       always=False)   )
        ret.append( util.Step(self.merge_portage,           always=False)   )
        ret.append( util.Step(self.setup_extras,            always=False)   )
        ret.append( util.Step(self.merge_system,            always=False)   )
        ret.append( util.Step(self.merge_packages,          always=False)   )
        if self.kernel:
            ret.append( util.Step(self.merge_kernel,        always=False)   )
        ret.append( util.Step(self.run_scripts,             always=False)   )
        ret.append( util.Step(self.remove_sources,          always=True)    )
        ret.append( util.Step(self.finish_sources,          always=True)    )
        ret.append( util.Step(self.install_portage_conf,    always=False)   )
        ret.append( util.Step(self.restore_profile_link,    always=True)    )
        ret.append( util.Step(self.clean_tmp,               always=True)    )
        ret.append( util.Step(self.pack,                    always=False)   )
        return ret

    def merge_portage(self):
        self._emerge('sys-apps/portage', flags='--oneshot --newuse')

    def setup_extras(self):
        util.chroot(
            path = self.target_root,
            function = util.cmd,
            fargs = {
                'cmdline': '%s/inhibitor-run.sh setup_extras' % ( self.env['INHIBITOR_SCRIPT_ROOT'], ),
                'env':      self.env,
            },
            failuref = self.chroot_failure,
        )

    def merge_system(self):
        self._emerge('system', flags='--deep --newuse --update')

    def merge_packages(self):
        package_str = ' '.join(self.package_list)
        package_str = package_str.replace('\n', ' ')
        self._emerge(package_str, flags='--deep --newuse --update')

    def merge_kernel(self):
        args = ['--build_name', self.build_name,
            '--kernel_pkg', '\'%s\'' % (self.kernel.kernel_pkg,)]

        if self.kernel.has('genkernel'):
            args.extend(['--genkernel', self.kernel.genkernel])
        if self.kernel.has('packages'):
            args.extend(['--packages', self.kernel.packages])

        util.chroot(
            path = self.target_root,
            function = util.cmd,
            fargs = {
                'cmdline': '%s/kernel.sh %s' % ( self.env['INHIBITOR_SCRIPT_ROOT'], ' '.join(args),),
                'env': self.env
            },
            failuref = self.chroot_failure,
        )

    def run_scripts(self):
        for script in self.scripts:
            script.install( root = self.target_root )
            util.chroot(
                path = self.target_root,
                function = util.cmd,
                fargs = {'cmdline': script.cmdline(), 'env':self.env},
                failuref = self.chroot_failure
            )

    def remove_sources(self):
        super(Stage4, self).remove_sources()
        for script in self.scripts:
            script.remove()

    def finish_sources(self):
        super(Stage4, self).finish_sources()
        for script in self.scripts:
            script.finish()

    def install_portage_conf(self):
        portage_cr = self.target_root.pjoin( self.env['PORTAGE_CONFIGROOT'] + '/etc/' )
        dest = self.target_root.pjoin('/etc/')
        util.path_sync(portage_cr, dest)

