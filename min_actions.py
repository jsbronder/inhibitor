import os
import shutil
import glob
import types
import re
import magic

import actions
import util

class InhibitorMinStage(actions.InhibitorStage):
    """
    Required:
        - InhibitorStage Requirements
    Optional:
        - package_list:   string/list of packages to add.
        - fs_add:     InhibitorSource, installed as last step over minroot.
        - files:      Files (aside from /bin/busybox) to add to minroot.
                      String or list of globable items.  Symlinks are handled.
        - TODO:  kernel, bbconfig
    """
    def __init__(self, stage_conf, build_name, stage_name='minimal_stage', **keywds):
        self.package_list   = []
        self.files          = []
        self.symlinks       = {}
        self.full_minroot   = None
        self.full_minstage  = None
        self.fs_add         = None
        self.copied_libs    = []
        self.checked_ldd    = []

        super(InhibitorMinStage, self).__init__(stage_conf, build_name, stage_name='min', **keywds)

        # We merge packages to here first, using ROOT=''
        self.minstage       = util.Path('/tmp/inhibitor/minstage')
        # Specific files from minstage are copied here to create
        # the minimal image.
        self.minroot        = util.Path('/tmp/inhibitor/minroot')

        self.portage_cf = self.minstage
        self.env.update({
            'PORTAGE_CONFIGROOT':   self.portage_cf,
        })
        self.root_env = {}
        self.root_env.update(self.env)
        self.root_env['ROOT'] = self.minstage
 
        self.lddre = re.compile("(/[^ ]*.so[^ ]*)")
        self.ms = magic.open(magic.MAGIC_NONE)
        self.ms.load()
        self.ms.setflags(magic.MAGIC_MIME)

    def post_conf(self, inhibitor_state):
        super(InhibitorMinStage, self).post_conf(inhibitor_state)
        self.full_minstage  = self.builddir.pjoin(self.minstage)
        self.full_minroot   = self.builddir.pjoin(self.minroot)
        if self.fs_add:
            self.fs_add.post_conf(inhibitor_state)
 
    def parse_config(self):
        super(InhibitorMinStage, self).parse_config()

        if self.conf.has('package_list'):
            if type(self.conf.package_list) == types.StringType:
                self.package_list = self.conf.package_list.split(' ')
            elif type(self.conf.package_list) == types.ListType:
                self.package_list = self.conf.package_list[:]
            else:
                raise util.InhibitorError("Packages must be either a string or a list")

        if self.conf.has('fs_add'):
            self.fs_add = self.conf.fs_add
            self.fs_add.dest = self.minroot
            self.fs_add.keep = True

        self.files = []
        if self.conf.has('files'):
            if type(self.conf.files) == types.StringType:
                for line in self.conf.files.splitlines():
                    line = line.lstrip('\t ').rstrip('\t ')
                    if len(line) > 0:
                        self.files.extend(line.split('\t '))
            elif type(self.conf.files) == types.ListType:
                self.files.extend(self.conf.files)
            else:
                raise util.InhibitorError("Files must be either a string or a list")
        self.files.insert(0, '/bin/busybox')

    
    def get_action_sequence(self):
        ret = self.setup_sequence[:]
        ret.append( util.Step(self.prep_dirs,           always=False) )
        ret.append( util.Step(self.merge_busybox,       always=False) )
        if self.conf.has('package_list'):
            ret.append( util.Step(self.merge_packages,  always=False) )
        ret.append( util.Step(self.copy_files,          always=False) )
        ret.append( util.Step(self.install_busybox,     always=False) )
        if self.conf.has('fs_add'):
            ret.append( util.Step(self.install_fs_add,  always=False) )
        ret.append( util.Step(self.pack,            always=False) )
        ret.extend( self.cleanup_sequence )
        return ret

    def prep_dirs(self):
        for d in ('dev', 'bin', 'sbin', 'proc', 'sys', 'etc'):
            for i in (self.full_minroot, self.full_minstage):
                t = i.pjoin(d)
                if not os.path.exists(t):
                    os.makedirs(t)
       
        libpath = self.builddir.pjoin('lib')
        if os.path.islink( libpath ):
            os.symlink(os.readlink(libpath), self.full_minroot.pjoin('lib'))
            os.symlink(os.readlink(libpath), self.full_minstage.pjoin('lib'))
            os.makedirs( os.path.realpath(libpath).replace(self.builddir, self.full_minroot))
            os.makedirs( os.path.realpath(libpath).replace(self.builddir, self.full_minstage))
            

    def merge_busybox(self):
        env = {}
        use = ''
        if 'USE' in self.env:
            use = self.env['USE']

        if len(self.package_list) == 0:
            use += ' static'
        use += ' make-symlinks'
        env.update(self.root_env)
        env['USE'] = use 
        
        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {
                'cmdline':
                    '/tmp/inhibitor/sh/inhibitor-run.sh run_emerge --newuse --nodeps sys-apps/busybox',
                'env':env,
            },
            failuref = self._chroot_failure
        )

    def merge_packages(self):
        ir = '/tmp/inhibitor/sh/inhibitor-run.sh'
        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {
                'cmdline':
                    '%s run_emerge --newuse --onlydeps %s' % (ir, ' '.join(self.package_list)),
                'env':self.env
            },
            failuref = self._chroot_failure
        )

        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {
                'cmdline':
                    '%s run_emerge --newuse %s' % (ir, ' '.join(self.package_list)),
                'env':self.root_env,
            },
            failuref = self._chroot_failure
        )

    def _ldlibs(self, binp):
        binp = binp.replace(self.full_minstage, '')

        if binp in self.checked_ldd:
            return []
        self.checked_ldd.append(binp)

        rc, output = util.chroot(
                path = self.full_minstage,
                function = util.cmd_out,
                fargs = {
                    'cmdline':          'ldd %s' % (binp,),
                    'raise_exception':   False,
                    'shell':             '/bin/ash',
                },
                failuref = self._chroot_failure
            )
        if rc != 0:
            return []
        libs = []
        for line in output.splitlines():
            try:
                lib = self.lddre.search(line).group(1)
            except (IndexError, AttributeError):
                continue
            if not lib in self.copied_libs:
                self.copied_libs.append(lib)
                libs.append( self.full_minstage.pjoin(lib) )
        return libs

    def path_sync_callback(self, src, targ):
        try:
            mime_type = self.ms.file(src).split(';')[0]
        except AttributeError:
            return 
        if not mime_type in ('application/x-executable', 'application/x-sharedlib'):
            return 
        needed_libs = self._ldlibs(src)
        for needed_lib in needed_libs:
            util.path_sync(
                needed_lib,
                needed_lib.replace(self.full_minstage, self.full_minroot),
                root = self.full_minstage,
                file_copy_callback = self.path_sync_callback
            )
         
    def copy_files(self):
        fix_slash = re.compile('///*')

        # Required for ldd
        m = util.Mount('/dev', '/dev', self.full_minstage)
        util.mount(m, self.istate.mount_points)

        for min_path in self.files:
            full_glob = self.full_minstage + '/' + min_path
            full_glob = fix_slash.sub('/', full_glob)

            for path in glob.iglob( full_glob ):
                if not os.path.lexists(path):
                    util.warn('Path %s does not exist' % (min_path,))
                    continue
                util.path_sync(
                    path,
                    path.replace(self.full_minstage, self.full_minroot),
                    root = self.full_minstage,
                    file_copy_callback = self.path_sync_callback
                )
        util.umount(m, self.istate.mount_points)


    def install_busybox(self):
        ash_link = self.full_minroot.pjoin('/bin/ash')
        if os.path.exists(ash_link):
            os.unlink(ash_link)
        os.symlink('busybox', self.full_minroot.pjoin('/bin/ash'))

        # Busybox install reads the /proc/self/exe links
        m = util.Mount('/proc', '/proc', self.full_minroot)
        util.mount(m, self.istate.mount_points)

        util.chroot(
            path = self.full_minroot,
            function = util.cmd,
            fargs = {
                'cmdline': '/bin/busybox --install -s /bin',
                'shell': '/bin/ash',
            },
            failuref = self._chroot_failure
        )
        util.umount(m, self.istate.mount_points)

    def install_fs_add(self):
        self.conf.fs_add.fetch()
        self.conf.fs_add.install()

    def pack(self):
        curdir = os.path.realpath(os.curdir)
        os.chdir(self.full_minroot)
        util.cmd('find ./ | cpio -H newc -o | gzip -c -9 > %s/minimage-%s.gz'
            % (self.builddir, self.build_name))
        os.chdir(curdir)


