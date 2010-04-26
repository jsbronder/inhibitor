import os
import shutil
import time
#from source import InhibitorSource
import util
import source

class InhibitorAction(object):
    """
    Basic action.  Handles running through the action_sequence and catching
    errors that can be passed back up in order to do cleaning first.

    @param name     - String representing this action
    """
    def __init__(self, name='BlankAction'):
        self.name = name
        self.action_sequence = []

    def post_conf(self, inhibitor_state):
        pass

    def run(self):
        for action in self.action_sequence:
            # Errors are caught by Inhibitor()
            util.dbg("Running %s" % action)
            func = getattr(self, action)
            func()

class CreateSnapshotAction(InhibitorAction):
    def __init__(self, snapshot_source):
        super(CreateSnapshotAction, self).__init__('mksnapshot')
        self.src = snapshot_source
        self.action_sequence = ['fetch', 'pack']

    def post_conf(self, inhibitor_state):
        self.src.post_conf(inhibitor_state)

    def fetch(self):
        self.src.fetch()

    def pack(self):
        tarfile = self.src.pack()
        util.info('%s is ready.' % tarfile)


class InhibitorStage(InhibitorAction):
    def __init__(self, stage_conf, build_name, stage_name='generic_stage'):
        super(InhibitorStage, self).__init__('stage')
        self.conf   = stage_conf
        self.istate = None
        self.action_sequence = [
            'get_sources',  'unpack_seed',      'sync_sources',
            'profile_link', 'write_make_conf',  'setup_chroot',
            'chroot',       'clean_sources','cleanup'
        ]
        self.sources = []
        self.stage_name = stage_name
        self.build_name = '%s-%s' %  (stage_name, build_name)
        self.ex_cflags      = []
        self.ex_cxxflags    = []
        self.ex_features    = []
        self.ex_overlays    = []

        if self.conf.has('snapshot'):
            self.conf.snapshot.keep = False
            self.conf.snapshot.dest = util.Path('/usr/portage')
            self.sources.append(self.conf.snapshot)

        if self.conf.has('overlays'):
            i = 0
            for overlay in self.conf.overlays:
                overlay.keep = False
                overlay.dest = util.Path('/usr/local/overlay-%d' % i)
                i += 1
                self.sources.append(overlay)
                self.ex_overlays.append(overlay.dest)

        if self.conf.has('portage_conf'):
            self.conf.portage_conf.keep = True
            self.conf.portage_conf.dest = util.Path('/etc/portage')
            self.sources.append(self.conf.portage_conf)

        if self.conf.has('make_conf'):
            self.conf.make_conf.keep = True
            self.conf.make_conf.dest = util.Path('/etc/make.conf')
            self.sources.append(self.conf.make_conf)
        else:
            self.ex_cflags.extend(['-O2', '-pipe'])
            self.ex_cxxflags.extend(['-O2', '-pipe'])

               
    def post_conf(self, inhibitor_state):
        self.istate     = inhibitor_state
        self.builddir   = self.istate.paths.build.pjoin(self.build_name)
        self.seed       = self.istate.paths.stages.pjoin(self.conf.seed)
        self.distdir    = self.istate.paths.dist

        # Update state
        self.istate.paths.chroot = self.builddir

        pkgdir          = self.istate.paths.pkgs.pjoin(self.build_name)
        distdir         = self.istate.paths.dist
        self.pkg_mount  = util.Mount(pkgdir, '/tmp/inhibitor/pkgs', self.builddir)
        self.dist_mount = util.Mount(distdir, '/tmp/inhibitor/dist', self.builddir)
        for d in (pkgdir, distdir):
            if not os.path.exists(d):
                util.dbg("Creating %s" % (d,))
                os.makedirs(d)

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
            src.install()

    def profile_link(self):
        targ = self.builddir.pjoin('/etc/make.profile')
        if os.path.exists(targ):
            os.unlink(targ)
        os.symlink('../usr/portage/profiles/%s' % self.conf.profile,
            self.builddir.pjoin('/etc/make.profile'))

    def write_make_conf(self):  
        need_keys = ['CFLAGS', 'CXXFLAGS', 'FEATURES', 'PORTDIR_OVERLAY']
        shutil.copyfile(
            self.builddir.pjoin('/etc/make.conf'),
            self.builddir.pjoin('/etc/make.conf.orig'))

        makeconf = util.make_conf_dict(self.builddir.pjoin('/etc/make.conf'))
        for k in need_keys:
            if not k in makeconf.keys():
                makeconf[k] = ""

        for v in self.ex_cflags:
            if not v in makeconf['CFLAGS']:
                makeconf['CFLAGS'] += ' ' + v

        for v in self.ex_cxxflags:
            if not v in makeconf['CXXFLAGS']:
                makeconf['CXXFLAGS'] += ' ' + v

        for v in self.ex_features:
            if not v in makeconf['FEATURES']:
                makeconf['FEATURES'] += ' ' + v

        for v in self.ex_overlays:
            if not v in makeconf['PORTDIR_OVERLAY']:
                makeconf['PORTDIR_OVERLAY'] += ' ' + v

        makeconf['PKGDIR'] = self.pkg_mount.dest
        makeconf['DISTDIR'] = self.dist_mount.dest

        for k in makeconf.keys():
            if makeconf[k] == "":
                del(makeconf[k])
        
        util.write_dict_bash(makeconf, self.builddir.pjoin('/etc/make.conf'))
        util.write_dict_bash(makeconf, self.builddir.pjoin('/etc/make.conf.inhibitor'))


    def setup_chroot(self):
        dest = self.builddir.pjoin('tmp/inhibitor')
        if not os.path.isdir(dest):
            os.mkdir(dest)

        for f in ('/etc/hosts', '/etc/resolv.conf'):
            shutil.copyfile(f, self.builddir.pjoin(f))

        for f in ('inhibitor-run.sh', 'inhibitor-functions.sh'):
            shutil.copy(self.istate.paths.share.pjoin('sh/'+f), dest)

        for m in ('/proc', '/dev', '/sys'):
            mount = util.Mount(m, m, self.builddir)
            util.mount(mount, self.istate.mount_points)

        util.mount(self.pkg_mount, self.istate.mount_points)
        util.mount(self.dist_mount, self.istate.mount_points)

    def chroot(self):
        try:
            util.cmd('chroot %s /tmp/inhibitor/inhibitor-run.sh run_%s' 
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
    def __init__(self, stage_conf, build_name):
        super(InhibitorStage4, self).__init__(stage_conf, build_name, stage_name='stage4')
        
        if self.conf.has('package_list'):
            self.packages = self.conf.package_list()
        else:
            self.packages = ['system']

    def setup_chroot(self):
        super(InhibitorStage4, self).setup_chroot()
        f = open(self.builddir.pjoin('tmp/inhibitor/package_list'), 'w')
        for pkg in self.packages:
            f.write('%s\n' %(pkg,))
        f.close()











