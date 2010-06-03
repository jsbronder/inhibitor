import os
import glob
import types
import re
import magic
import tarfile
import shutil

import actions
import util
import source

class InhibitorMinStage(actions.InhibitorStage):
    """
    Required:
        - InhibitorStage Requirements
    Optional:
        - package_list:   string/list of packages to add.
        - fs_add:     InhibitorSource, installed as last step over minroot.
        - files:      Files (aside from /bin/busybox) to add to minroot.
                      String or list of globable items.  Symlinks are handled.
        - TODO:  kernel?
    """
    def __init__(self, stage_conf, build_name, stage_name='minimal_stage', **keywds):
        self.package_list   = []
        self.files          = []
        self.symlinks       = {}
        self.full_minroot   = None
        self.full_minstage  = None
        self.tarpath        = None
        self.cpiopath       = None
        self.fs_add         = None
        self.baselayout     = None
        self.copied_libs    = []
        self.checked_ldd    = []
        self.modules        = []
        self.moduledir      = None

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

        self.sh_scripts.append('kernel.sh')
        self.kerndir = util.Path('/tmp/inhibitor/kerncache')



    def post_conf(self, inhibitor_state):
        super(InhibitorMinStage, self).post_conf(inhibitor_state)
        self.full_minstage  = self.builddir.pjoin(self.minstage)
        self.full_minroot   = self.builddir.pjoin(self.minroot)
        self.moduledir      = inhibitor_state.paths.share.pjoin('sh/early-userspace/modules')
        self.tarpath        = self.istate.paths.stages.pjoin('%s/image.tar.bz2' % (self.build_name,))
        self.cpiopath       = self.istate.paths.stages.pjoin('%s/initramfs.gz' % (self.build_name,))

        if self.fs_add:
            self.fs_add.post_conf(inhibitor_state)
        kerndir = self.istate.paths.kernel.pjoin(self.build_name)
        self.ex_mounts.append(util.Mount(kerndir, self.kerndir, self.builddir))

        self.baselayout     = source.InhibitorSource(
            'file://%s/sh/early-userspace/root' % inhibitor_state.paths.share,
            keep = True,
            dest = self.minroot
        )
        self.baselayout.post_conf(inhibitor_state)

        for m in self.modules:
            need_file = self.moduledir.pjoin('%s.files' % m)
            pkg_file = self.moduledir.pjoin('%s.pkgs' % m)
            if os.path.lexists(need_file):
                f = open(need_file)
                for l in f.readlines():
                    self.files.append(l.strip())
                    util.dbg('Adding path %s for %s' % (l.strip(), m))
                f.close()
            if os.path.lexists(pkg_file):
                f = open(pkg_file)
                for l in f.readlines():
                    self.package_list.append(l.strip())
                    util.dbg('Adding package %s for %s' % (l.strip(), m))
                f.close()
 
 
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

        if self.conf.has('modules'):
            self.modules = self.conf.modules

        # Put at the beginning of the list so the user can still overwrite these.
        self.files.insert(0, '/bin/busybox')

        if self.conf.has('kernel'):
            if not self.conf.kernel.has('kconfig'):
                raise util.InhibitorError("No kconfig specified for kernel")
            else:
                self.conf.kernel.kconfig.keep = True
                self.conf.kernel.kconfig.dest = util.Path('/tmp/inhibitor/kconfig')
                self.sources.append(self.conf.kernel.kconfig)
            if not self.conf.kernel.has('kernel_pkg'):
                raise util.InhibitorError('No kernel_pkg specfied for kernel')

    
    def get_action_sequence(self):
        ret = self.setup_sequence[:]
        ret.append( util.Step(self.prep_minroot,        always=False) )
        ret.append( util.Step(self.merge_busybox,       always=False) )
        if self.conf.has('package_list'):
            ret.append( util.Step(self.merge_packages,  always=False) )
        ret.append( util.Step(self.copy_files,          always=False) )
        ret.append( util.Step(self.install_busybox,     always=False) )
        ret.append( util.Step(self.install_modules,     always=False) )
        if self.conf.has('fs_add'):
            ret.append( util.Step(self.install_fs_add,  always=False) )
        if self.conf.has('kernel'):
            ret.append( util.Step(self.build_kernel,    always=False) )
        ret.append( util.Step(self.update_init,         always=False) )
        ret.append( util.Step(self.pack,                always=False) )
        ret.extend( self.cleanup_sequence )
        ret.append( util.Step(self.final_report,        always=True)  )
        return ret

    def prep_minroot(self):
        for d in ('dev', 'bin', 'sbin', 'proc', 'sys', 'etc', '/tmp',
                    'usr/sbin', 'usr/bin', 'etc/rc.d', 'etc/conf.d'):
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

        self.baselayout.fetch()
        self.baselayout.install( root=self.builddir )
            

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
                    '%s run_emerge --newuse %s' % (ir, ' '.join(self.package_list)),
                'env':self.env
            },
            failuref = self._chroot_failure
        )

        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {
                'cmdline':
                    '%s run_emerge --newuse --nodeps %s' % (ir, ' '.join(self.package_list)),
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
            if '*' in min_path:
                full_glob = self.full_minstage + '/' + min_path
                full_glob = fix_slash.sub('/', full_glob)
                files = glob.glob( full_glob )
            else:
                files = [ self.full_minstage.pjoin(min_path) ]

            for path in files:
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
                'cmdline': '/bin/busybox --install -s',
                'shell': '/bin/ash',
            },
            failuref = self._chroot_failure
        )
        util.umount(m, self.istate.mount_points)

    def install_modules(self):
        for m in self.modules:
            init = self.moduledir.pjoin('%s.init' % m)
            conf = self.moduledir.pjoin('%s.conf' % m)
            if os.path.exists(init):
                shutil.copy2(init, self.full_minroot.pjoin('etc/init.d/%s' % m))
            if os.path.exists(conf):
                shutil.copy2(conf, self.full_minroot.pjoin('etc/conf.d/%s' % m))

    def install_fs_add(self):
        self.conf.fs_add.fetch()
        self.conf.fs_add.install( root=self.builddir )

    def update_init(self):
        for initd in glob.iglob('%s/*' % self.full_minroot.pjoin('etc/init.d')):
            int_path = initd.replace(self.full_minroot, '')
            util.dbg('Adding %s to init' % int_path)
            util.chroot(
                path = self.full_minroot,
                function = util.cmd,
                fargs = {
                    'cmdline':  '%s enable' % int_path,
                    'shell':    '/bin/ash'
                },
                failuref = self._chroot_failure,
            )

    def pack(self):
        basedir = os.path.dirname(self.tarpath)
        if not os.path.lexists(basedir):
            os.makedirs(basedir)

        archive = tarfile.open(self.tarpath, 'w:bz2')
        archive.add(self.full_minroot,
            arcname = '/',
            recursive = True
        )
        archive.close()

        curdir = os.path.realpath(os.curdir)
        os.chdir(self.full_minroot)
        util.cmd('find ./ | cpio -H newc -o | gzip -c -9 > %s' % (self.cpiopath))
        os.chdir(curdir)

        if self.conf.has('kernel'):
            kernel_link = self.builddir.pjoin('/tmp/inhibitor/kernelbuild/boot/kernel')
            kernel_path = os.path.join( os.path.dirname(kernel_link), os.readlink(kernel_link))
            
            shutil.copy2(kernel_path, os.path.join(basedir, os.path.basename(kernel_path)) )
            link_path = os.path.join(basedir, 'kernel')
            if os.path.lexists(link_path):
                os.unlink(link_path)
            os.symlink(os.path.basename(kernel_path), link_path)

    def build_kernel(self):
        env = {}
        env.update(self.env)
        env['ROOT'] = '/tmp/inhibitor/kernelbuild'

        if not os.path.lexists( env['ROOT'] ):
            os.makedirs( env['ROOT'] )

        args = ['--build_name', self.build_name,
            '--kernel_pkg', self.conf.kernel.kernel_pkg]
        util.chroot(
            path = self.builddir,
            function = util.cmd,
            fargs = {
                'cmdline': '/tmp/inhibitor/sh/kernel.sh %s' % (' '.join(args),),
                'env': env
            },
            failuref = self._chroot_failure,
        )

    def final_report(self):
        util.info("Created %s" % (self.tarpath,))
        util.info("Created %s" % (self.cpiopath,))
        if self.conf.has('kernel'):
            util.info("Kernel copied into %s" % (os.path.dirname(self.tarpath),) )
