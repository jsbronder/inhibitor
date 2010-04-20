import os
import shutil

#from source import InhibitorSource
import util

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
            'profile_link', 'setup_chroot',     'chroot',
            'clean_sources','cleanup'
        ]
        self.sources = []
        self.stage_name = stage_name
        self.build_name = '%s-%s' %  (stage_name, build_name)
        
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

        if self.conf.has('portage_conf'):
            self.conf.portage_conf.keep = True
            self.conf.portage_conf.dest = util.Path('/etc/portage')
            self.sources.append(self.conf.portage_conf)

        if self.conf.has('make_conf'):
            self.conf.make_conf.keep = True
            self.conf.make_conf.dest = util.Path('/etc/')
            self.sources.append(self.conf.make_conf)
                
    def post_conf(self, inhibitor_state):
        self.istate     = inhibitor_state
        self.builddir   = self.istate.paths.build.join(self.build_name)
        self.seed       = self.istate.paths.stages.join(self.conf.seed)
        self.pkgdir     = self.istate.paths.pkgs.join(self.build_name)
        # Update state
        self.istate.paths.chroot = self.builddir

        for src in self.sources:
            src.post_conf(inhibitor_state)

        if not os.path.exists(self.pkgdir):
            util.warn("Package cache %s does not exist yet.")
            os.makedirs(self.pkgdir)


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
        targ = self.builddir.join('/etc/make.profile')
        if os.path.exists(targ):
            os.unlink(targ)
        os.symlink('../usr/portage/profiles/%s' % self.conf.profile,
            self.builddir.join('/etc/make.profile'))

    def setup_chroot(self):
        dest = self.builddir.join('tmp/inhibitor')
        os.mkdir(dest)

        for f in ('/etc/hosts', '/etc/resolv.conf'):
            shutil.copyfile(f, self.builddir.join(f))

        for f in ('inhibitor-run.sh', 'inhibitor-functions.sh'):
            shutil.copy(self.istate.paths.share.join('sh/'+f), dest)

        for m in ('/proc', '/dev', '/sys'):
            mount = util.Mount(m, m, self.builddir)
            util.mount(mount, self.istate.mount_points)

        mount = util.Mount(
            self.pkgdir,
            '/tmp/pkgs',
            self.builddir)
        util.mount(mount, self.istate.mount_points)

    def chroot(self):
        try:
            util.cmd('chroot %s /tmp/inhibitor/inhibitor-run.sh run_%s' 
                % (self.builddir, self.stage_name))
        except Exception, e:
            util.umount_all(self.istate.mount_points)
            raise

    def clean_sources(self):
        for src in self.sources:
            src.clean()

    def cleanup(self):
        util.umount_all(self.istate.mount_points)
        shutil.rmtree(self.builddir.join('tmp/inhibitor'))
