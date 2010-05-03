import os
import shutil
import time
import util
import glob

class Step(util.Container):
    def __init__(self, function, always=True, **keywds):
        super(Step, self).__init__(function=function, always=always, **keywds)
        self.name = function.func_name

    def run(self):
        self.function()


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


class CreateSnapshotAction(InhibitorAction):
    def __init__(self, snapshot_source, **keywds):
        super(CreateSnapshotAction, self).__init__('snapshot-%s' % (snapshot_source.name,), **keywds)
        self.src = snapshot_source

    def get_action_sequence(self):
        return [
            Step(self.fetch,    always=False),
            Step(self.pack,     always=False),
        ]

    def post_conf(self, inhibitor_state):
        super(CreateSnapshotAction, self).post_conf(inhibitor_state)
        self.src.post_conf(inhibitor_state)

    def fetch(self):
        self.src.fetch()

    def pack(self):
        tarfile = self.src.pack()
        util.info('%s is ready.' % tarfile)


class InhibitorStage(InhibitorAction):
    def __init__(self, stage_conf, build_name, stage_name='generic_stage', **keywds):
        self.build_name = '%s-%s' %  (stage_name, build_name)
        super(InhibitorStage, self).__init__(self.build_name, **keywds)

        self.conf   = stage_conf
        self.istate = None

        self.setup_sequence = [
            Step(self.get_sources,      always=False),
            Step(self.unpack_seed,      always=False),
            Step(self.sync_sources,     always=True),
            Step(self.profile_link,     always=False),
            Step(self.write_make_conf,  always=False),
            Step(self.setup_chroot,     always=True),
        ]

        self.cleanup_sequence = [
            Step(self.clean_sources,    always=True),
            Step(self.cleanup,          always=True),
        ]
        
        self.sources = []
        self.stage_name = stage_name
        self.ex_mounts      = []
        self.builddir       = None
        self.seed           = None
        self.sh_scripts     = ['inhibitor-run.sh', 'inhibitor-functions.sh']

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
            self.conf.portage_conf.dest = util.Path('/etc/portage')
            self.sources.append(self.conf.portage_conf)

        self.ex_make_conf   = {
            'PKGDIR':       '/tmp/inhibitor/pkgs/',
            'DISTDIR':      '/tmp/inhibitor/dist/',
        }
        if len(portdir_overlay) > 0:
            self.ex_make_conf['PORTDIR_OVERLAY'] = ' '.join(portdir_overlay)

        if self.conf.has('make_conf'):
            self.conf.make_conf.keep = True
            self.conf.make_conf.dest = util.Path('/etc/make.conf')
            self.sources.append(self.conf.make_conf)
        else:
            self.ex_make_conf['CFLAGS']     = '-O2 -pipe'
            self.ex_make_conf['CXXFLAGS']   = '-O2 -pipe'

    def get_action_sequence(self):
        ret = self.setup_sequence[:]
        ret.append(self.chroot)
        ret.extend(self.cleanup_sequence)
        return ret
               
    def post_conf(self, inhibitor_state):
        super(InhibitorStage, self).post_conf(inhibitor_state)
        self.istate     = inhibitor_state
        self.builddir   = self.istate.paths.build.pjoin(self.build_name)
        self.seed       = self.istate.paths.stages.pjoin(self.conf.seed)

        # Update state
        self.istate.paths.chroot = self.builddir

        pkgdir          = self.istate.paths.pkgs.pjoin(self.build_name)
        distdir         = self.istate.paths.dist

        for i in ('/proc', '/sys', '/dev'):
            self.ex_mounts.append(util.Mount(i, i, self.builddir))
        
        self.ex_mounts.append(util.Mount(pkgdir,  self.ex_make_conf['PKGDIR'],  self.builddir))
        self.ex_mounts.append(util.Mount(distdir, self.ex_make_conf['DISTDIR'], self.builddir))
        
        for src in self.sources:
            src.post_conf(inhibitor_state)

    def get_sources(self):
        for src in self.sources:
            src.fetch()

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

        util.info("Syncing %s from %s" % (self.seed.dname(), self.builddir.dname()) )
        util.cmd('rsync -a --delete %s %s' % 
            (self.seed.dname(), self.builddir.dname()) )

    def sync_sources(self):
        for src in self.sources:
            if self.resume and src.keep:
                continue
            src.install()

    def profile_link(self):
        targ = self.builddir.pjoin('/etc/make.profile')
        if os.path.exists(targ):
            os.unlink(targ)
        os.symlink('../usr/portage/profiles/%s' % self.conf.profile,
            self.builddir.pjoin('/etc/make.profile'))

    def write_make_conf(self):  
        shutil.copyfile(
            self.builddir.pjoin('/etc/make.conf'),
            self.builddir.pjoin('/etc/make.conf.orig'))

        makeconf = util.make_conf_dict(self.builddir.pjoin('/etc/make.conf'))
        makeconf.update(self.ex_make_conf)

        for k in self.ex_make_conf.keys():
            if not k in makeconf.keys():
                makeconf[k] = self.ex_make_conf[k]
            else:
                for v in self.ex_make_conf[k].split(' '):
                    if not v in makeconf[k]:
                        makeconf[k] += ' ' + v
        
        util.write_dict_bash(makeconf, self.builddir.pjoin('/etc/make.conf'))
        util.write_dict_bash(makeconf, self.builddir.pjoin('/etc/make.conf.inhibitor'))


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
                util.warn("Creating %s, required for a bind mount.")
                os.makedirs(m.src)
            util.mount(m, self.istate.mount_points)

    def chroot(self):
        try:
            util.cmd('chroot %s /tmp/inhibitor/sh/inhibitor-run.sh run_%s' 
                % (self.builddir, self.stage_name))
        except (KeyboardInterrupt, SystemExit):
            util.info("Caught SIGTERM or SIGINT:  Waiting for children to die")
            # XXX:  Hacky.
            time.sleep(5)
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError("Caught KeyboardInterrupt or SystemExit")
        except Exception, e:
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError(str(e))

    def clean_sources(self):
        for src in self.sources:
            src.clean()

    def cleanup(self):
        util.umount_all(self.istate.mount_points)
        shutil.rmtree(self.builddir.pjoin('tmp/inhibitor'))
        shutil.copyfile(
            self.builddir.pjoin('/etc/make.conf.orig'),
            self.builddir.pjoin('/etc/make.conf'))



class InhibitorStage4(InhibitorStage):
    def __init__(self, stage_conf, build_name, **keywds):
        super(InhibitorStage4, self).__init__(stage_conf, build_name, stage_name='stage4', **keywds)

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
        ret.extend([
            Step(self.chroot,           always=False),
            Step(self.install_kernel,   always=False),
            Step(self.run_scripts,      always=False)
        ])
        ret.extend(self.cleanup_sequence)
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

        try:
            util.cmd('chroot %s /tmp/inhibitor/sh/kernel.sh %s'
                % (self.builddir, ' '.join(args)) )
        except (KeyboardInterrupt, SystemExit):
            util.info("Caught SIGTERM or SIGINT:  Waiting for children to die")
            # XXX:  Hacky.
            time.sleep(5)
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError("Caught KeyboardInterrupt or SystemExit")
        except Exception, e:
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError(str(e))

    def run_scripts(self):        
        for script in self.scripts:
            script.install()
            script.run( chroot=self.builddir )

