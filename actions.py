import os
import shutil
import util
import glob
import tarfile
import types

class InhibitorAction(object):
    """
    Basic action.  Handles running through the action_sequence and catching
    errors that can be passed back up in order to do cleaning first.

    @param name     - String representing this action
    """
    def __init__(self, name='BlankAction', resume=False):
        self.name = name
        self.action_sequence = []
        self.resume = resume
        self.statedir = None

    def get_action_sequence(self):
        return []

    def post_conf(self, inhibitor_state):
        self.statedir = inhibitor_state.paths.state.pjoin(self.name)
        if os.path.isdir(self.statedir) and not self.resume:
            self.clear_resume()
            os.makedirs(self.statedir)
        elif not os.path.exists(self.statedir):
            os.makedirs(self.statedir)
            self.resume = False
        elif len(os.listdir(self.statedir)) == 0:
            self.resume = False

    def run(self):
        for action in self.get_action_sequence():
            resume_path = self.statedir.pjoin('resume-%s-%s' % (self.name, action.name))
            if ( self.resume 
                    and action.always == False 
                    and os.path.exists(resume_path) ):
                continue
            # Errors are caught by Inhibitor()
            util.info("Running %s" % action.name)
            action.run()
            open(resume_path, 'w').close()
        self.clear_resume()

    def clear_resume(self):
        for f in glob.iglob(self.statedir.pjoin('resume-%s-*' % self.name)):
            os.unlink(f)
        os.rmdir(self.statedir)


class InhibitorSnapshot(InhibitorAction):
    def __init__(self, snapshot_source, name, exclude=None, include=None):
        super(InhibitorSnapshot, self).__init__(name='snapshot')
        self.dest       = None
        self.builddir   = None
        self.tarname    = None
        self.dest       = None

        self.name       = name
        self.src        = snapshot_source
        self.src.keep   = True
        self.src.dest   = util.Path('/')

        if exclude:
            if type(exclude) == types.StringType:
                self.exclude = exclude.split(' ')
            elif type(exclude) in (types.ListType, types.TupleType):
                self.exclude = exclude
            else:
                raise util.InhibitorError("Unrecognized exclude pattern.")
        else:
            self.exclude = False

        if include:
            if type(include) == types.StringType:
                self.include = include.split(' ')
            elif type(include) in (types.ListType, types.TupleType):
                self.include = include
            else:
                raise util.InhibitorError("Unrecognized include pattern.")
        else:
            self.include = False

    def get_action_sequence(self):
        return [
            util.Step(self.sync,     always=False),
            util.Step(self.pack,     always=False),
        ]

    def post_conf(self, inhibitor_state):
        super(InhibitorSnapshot, self).post_conf(inhibitor_state)
        self.src.post_conf(inhibitor_state)
        self.src.init()

        self.tarname    = 'snapshot-' + self.name
        self.dest       = inhibitor_state.paths.stages.pjoin(self.tarname+'.tar.bz2')
        self.builddir   = inhibitor_state.paths.build.pjoin(self.tarname)

    def sync(self):
        if os.path.exists(self.builddir):
            shutil.rmtree(self.builddir)
        elif os.path.islink(self.builddir):
            os.unlink(self.builddir)
        os.makedirs(self.builddir)

        exclude_cmd = ''
        if self.exclude:
            for i in self.exclude:
                exclude_cmd += " --exclude='%s'" % i

        if self.include:
            for pattern in self.include:
                paths = [self.src.cachedir.pjoin(pattern)]
                if '*' in pattern:
                    paths = glob.glob(self.src.cachedir.pjoin(pattern))

                for path in paths:
                    dest = path.replace(self.src.cachedir, self.builddir)
                    if not os.path.lexists( os.path.dirname(dest) ):
                        os.makedirs( os.path.dirname(dest) )
                    util.cmd('rsync -a %s %s/ %s/' % (
                        exclude_cmd,
                        path,
                        dest
                    ))
        else:
            util.cmd('rsync -a %s %s/ %s/' % (exclude_cmd, self.src.cachedir, self.builddir))

    def pack(self):
        archive = tarfile.open(self.dest, 'w:bz2')
        archive.add(self.builddir,
            arcname = '/',
            recursive = True
        )
        archive.close()
        util.info('%s is ready.' % self.dest)


class InhibitorStage(InhibitorAction):
    def __init__(self, stage_conf, build_name, stage_name='generic_stage', **keywds):
        self.build_name = '%s-%s' %  (stage_name, build_name)
        super(InhibitorStage, self).__init__(self.build_name, **keywds)

        self.conf   = stage_conf
        self.istate = None

        self.setup_sequence = [
            util.Step(self.unpack_seed,      always=False),
            util.Step(self.sync_sources,     always=True),
            util.Step(self.profile_link,     always=False),
            util.Step(self.write_make_conf,  always=False),
            util.Step(self.setup_chroot,     always=True),
        ]

        self.cleanup_sequence = [
            util.Step(self.clean_sources,    always=True),
            util.Step(self.cleanup,          always=True),
        ]
        
        self.sources = []
        self.stage_name = stage_name
        self.ex_mounts      = []
        self.builddir       = None
        self.seed           = None
        self.tarpath        = None
        self.sh_scripts     = ['inhibitor-run.sh', 'inhibitor-functions.sh']
        self.portage_cf     = util.Path('/')    # PORTAGE_CONFIGROOT

        self.ex_make_conf   = {
            'PKGDIR':       '/tmp/inhibitor/pkgs/',
            'DISTDIR':      '/tmp/inhibitor/dist/',
        }
        self.env = {
            'INHIBITOR_SCRIPT_ROOT':'/tmp/inhibitor/sh'
        }

    def _chroot_failure(self, **_):
        util.umount_all(self.istate.mount_points)
        
    def get_action_sequence(self):
        ret = self.setup_sequence[:]
        ret.append(self.chroot)
        ret.extend(self.cleanup_sequence)
        ret.append(util.Step(self.pack,             always=True))
        return ret

    def parse_config(self):
        if self.conf.has('snapshot'):
            self.conf.snapshot.keep = False
            self.conf.snapshot.dest = util.Path('/usr/portage')
            self.sources.append(self.conf.snapshot)

        portdir_overlay = []
        if self.conf.has('overlays'):
            i = 0
            for overlay in self.conf.overlays:
                overlay.keep = False
                overlay.dest = util.Path('/usr/local/overlay-%d' % i)
                i += 1
                self.sources.append(overlay)
                portdir_overlay.append(overlay.dest)

        if self.conf.has('portage_conf'):
            self.conf.portage_conf.keep = True
            self.conf.portage_conf.dest = util.Path('%s/etc/portage' % (self.portage_cf,))
            self.sources.append(self.conf.portage_conf)

        if len(portdir_overlay) > 0:
            self.ex_make_conf['PORTDIR_OVERLAY'] = ' '.join(portdir_overlay)

        if self.conf.has('make_conf'):
            self.conf.make_conf.keep = True
            self.conf.make_conf.dest = util.Path('%s/etc/make.conf' % (self.portage_cf,))
            self.sources.append(self.conf.make_conf)
        else:
            self.ex_make_conf['CFLAGS']     = '-O2 -pipe'
            self.ex_make_conf['CXXFLAGS']   = '-O2 -pipe'

    def post_conf(self, inhibitor_state):
        super(InhibitorStage, self).post_conf(inhibitor_state)
        self.parse_config()

        self.istate     = inhibitor_state
        self.builddir   = self.istate.paths.build.pjoin(self.build_name)
        self.seed       = self.istate.paths.stages.pjoin(self.conf.seed)
        self.tarpath    = self.istate.paths.stages.pjoin(self.build_name + '.tar.bz2')
        pkgdir          = self.istate.paths.pkgs.pjoin(self.build_name)
        distdir         = self.istate.paths.dist

        for i in ('/proc', '/sys', '/dev'):
            self.ex_mounts.append(util.Mount(i, i, self.builddir))
        
        self.ex_mounts.append(util.Mount(pkgdir,  self.ex_make_conf['PKGDIR'],  self.builddir))
        self.ex_mounts.append(util.Mount(distdir, self.ex_make_conf['DISTDIR'], self.builddir))
        
        for src in self.sources:
            src.post_conf(inhibitor_state)
            src.init()

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

        util.info("Syncing %s to %s" % (self.seed.dname(), self.builddir.dname()) )
        util.cmd('rsync -a --delete %s %s' % 
            (self.seed.dname(), self.builddir.dname()) )

    def sync_sources(self):
        for src in self.sources:
            src.install( root=self.builddir )

    def profile_link(self):
        targ = self.builddir.pjoin('%s/etc/make.profile' % (self.portage_cf,))
        if os.path.lexists(targ):
            os.unlink(targ)
        os.symlink('/usr/portage/profiles/%s' % self.conf.profile, targ)

    def write_make_conf(self):
        mc_path = self.builddir.pjoin('%s/etc/make.conf' % (self.portage_cf,))
        if os.path.exists( mc_path ):
            shutil.copyfile(mc_path, mc_path + '.orig')

        makeconf = util.make_conf_dict(mc_path)

        for k in self.ex_make_conf.keys():
            if not k in makeconf.keys():
                makeconf[k] = self.ex_make_conf[k]
            else:
                for v in self.ex_make_conf[k].split(' '):
                    if not v in makeconf[k]:
                        makeconf[k] += ' ' + v
        
        util.write_dict_bash(makeconf, mc_path)
        util.write_dict_bash(makeconf, mc_path + '.orig')


    def setup_chroot(self):
        dest = self.builddir.pjoin('tmp/inhibitor')
        if not os.path.isdir(dest.pjoin('sh')):
            os.makedirs(dest.pjoin('sh'))

        for f in ('/etc/hosts', '/etc/resolv.conf'):
            shutil.copyfile(f, self.builddir.pjoin(f))

        for f in self.sh_scripts:
            shutil.copy(self.istate.paths.share.pjoin('sh/'+f), dest.pjoin('sh'))

        for m in self.ex_mounts:
            if not os.path.isdir(m.src):
                util.warn("Creating %s, required for a bind mount." % (m.src,))
                os.makedirs(m.src)
            util.mount(m, self.istate.mount_points)

    def chroot(self):
        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {'cmdline':  '/tmp/inhibitor/sh/inhibitor-run.sh run_%s' % (self.stage_name,)},
            failuref = self._chroot_failure,
        )

    def clean_sources(self):
        for src in self.sources:
            src.remove()
            src.finish()

    def cleanup(self):
        util.umount_all(self.istate.mount_points)
        shutil.rmtree(self.builddir.pjoin('tmp/inhibitor'))
        mc_path = self.builddir.pjoin("%s/etc/make.conf" % (self.portage_cf,))
        if os.path.lexists(mc_path):
            shutil.copyfile(mc_path + '.orig', mc_path)

    def pack(self):
        archive = tarfile.open(self.tarpath, 'w:bz2')
        archive.add(self.builddir,
            arcname = '/',
            recursive = True
        )
        archive.close()
        util.info("Created %s" % (self.tarpath,))


class InhibitorStage4(InhibitorStage):
    def __init__(self, stage_conf, build_name, **keywds):
        if not 'stage_name' in keywds.keys():
            super(InhibitorStage4, self).__init__(stage_conf, build_name, stage_name='stage4', **keywds)
        else:
            super(InhibitorStage4, self).__init__(stage_conf, build_name, **keywds)

        self.kerndir = util.Path('/tmp/inhibitor/kerncache')
        self.sh_scripts.append('kernel.sh')
        
        if self.conf.has('package_list'):
            self.packages = self.conf.package_list()
        else:
            self.packages = ['system']

        self.scripts = []
        if self.conf.has('scripts'):
            self.scripts = self.conf.scripts

        if self.conf.has('kernel'):
            self.kernel = self.conf.kernel
            if not self.kernel.has('kconfig'):
                raise util.InhibitorError("No kconfig specified for kernel")
            else:
                self.kernel.kconfig.keep = True
                self.kernel.kconfig.dest = util.Path('/tmp/inhibitor/kconfig')
                self.sources.append(self.kernel.kconfig)
            if not self.kernel.has('kernel_pkg'):
                raise util.InhibitorError("No kernel_pkg specified for kernel")

    def get_action_sequence(self):
        ret = self.setup_sequence[:]
        ret.append( util.Step(self.chroot,               always=False) )
        if self.conf.has('kernel'):
            ret.append( util.Step(self.install_kernel,   always=False) )
        ret.append( util.Step(self.run_scripts,          always=False) )
        ret.extend(self.cleanup_sequence)
        ret.append(util.Step(self.pack,                  always=True)  )
        return ret

    def post_conf(self, inhibitor_state):
        super(InhibitorStage4, self).post_conf(inhibitor_state)
        for script in self.scripts:
            script.post_conf(inhibitor_state)

        kerndir = self.istate.paths.kernel.pjoin(self.build_name)
        self.ex_mounts.append(util.Mount(kerndir, self.kerndir, self.builddir))

    def setup_chroot(self):
        super(InhibitorStage4, self).setup_chroot()
        f = open(self.builddir.pjoin('tmp/inhibitor/package_list'), 'w')
        for pkg in self.packages:
            f.write('%s\n' %(pkg,))
        f.close()

    def chroot(self):
        super(InhibitorStage4, self).chroot()

    def install_kernel(self):
        args = ['--build_name', self.build_name,
            '--kernel_pkg', self.kernel.kernel_pkg]

        if self.kernel.has('genkernel'):
            args.extend(['--genkernel', self.kernel.genkernel])
        if self.kernel.has('packages'):
            args.extend(['--packages', self.kernel.packages])


        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {'cmdline': '/tmp/inhibitor/sh/kernel.sh %s' % (' '.join(args),)},
            failuref = self._chroot_failure,
        )

    def run_scripts(self):
        for script in self.scripts:
            script.install( root=self.builddir )
            util.chroot(
                path = self.builddir,
                function = util.cmd,
                fargs = {'cmdline': script.cmdline(), 'env':self.env},
                failuref = self._chroot_failure,
            )

    def clean_sources(self):
        super(InhibitorStage4, self).clean_sources()
        for script in self.scripts:
            script.remove()
            script.finish()

