import os
import glob
import re
import magic
import tarfile
import shutil

import stage
import util
import source

class EmbeddedStage(stage.BaseStage):
    """
    Create an Embedded Stage, essentially a stage4 based on busybox providing the majority
    of the required functionality.

    @param stage_conf   - Stage configuration, details below.
    @param build_name   - Unique string to identify the stage.

    Stage Configuration:
    @param name         - Should match the build_name.
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
    @param package_list - String or List of packages to install to
                          the working stage3.
    @param make_conf    - InhibitorSource for make.conf.
    @param fs_add       - InhibitorSource of files to add to the completed stage.
    @param files        - String or List of files that should be copied from the
                          working stage3 into the embedded stage.
    @param portage_conf - InhibitorSource with the contents for /etc/portage.
    @param modules      - Modules to add to the embedded stage.  Modules will add
                          init.d, conf.d files and packages as necessary to the
                          embedded stage automatically.
    """
    
    def __init__(self, stage_conf, build_name, **keywds):
        self.seed           = None
        self.tarpath        = None
        self.cpiopath       = None
        self.fs_add         = None
        self.files          = []
        self.copied_libs    = []
        self.checked_ldd    = []
        self.package_list   = []
        self.modules        = []
        self.moduledir      = None
        self.lddre          = re.compile("(/[^ ]*.so[^ ]*)")
        self.ms             = magic.open(magic.MAGIC_NONE)
        self.stage_sources  = []

        super(EmbeddedStage, self).__init__(stage_conf, build_name, 'embedded', **keywds)
        self.ms.load()
        self.ms.setflags(magic.MAGIC_MIME)

    
    def post_conf(self, inhibitor_state):
        if self.conf.has('seed'):
            self.seed = self.conf.seed

        if self.conf.has('fs_add'):
            self.conf.fs_add.keep = True
            self.conf.fs_add.dest = util.Path('/')
            self.stage_sources.append(self.conf.fs_add)

        baselayout     = source.create_source(
            src = 'file://%s/early-userspace/root' % inhibitor_state.paths.share,
            keep = True,
            dest = util.Path('/')
        )
        self.stage_sources.append(baselayout)

        for src in self.stage_sources:
            src.post_conf(inhibitor_state)
            src.init()

        super(EmbeddedStage, self).post_conf(inhibitor_state)
        self.moduledir      = self.istate.paths.share.pjoin('early-userspace/modules')
        self.tarpath        = self.istate.paths.stages.pjoin('%s/image.tar.bz2' % (self.build_name,))
        self.cpiopath       = self.istate.paths.stages.pjoin('%s/initramfs.gz' % (self.build_name,))

        if self.conf.has('files'):
            self.files = util.strlist_to_list(self.conf.files)

        if self.conf.has('package_list'):
            self.package_list = util.strlist_to_list(self.conf.package_list)

        if self.conf.has('modules'):
            self.modules = self.conf.modules

        for m in self.modules:
            need_file   = self.moduledir.pjoin('%s.files' % m)
            pkg_file    = self.moduledir.pjoin('%s.pkgs' % m)
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

    def get_action_sequence(self):
        ret = []
        if self.seed:
            ret.append( util.Step(self.unpack_seed,             always=False)   )
        ret.append( util.Step(self.install_sources,             always=True)    )
        ret.append( util.Step(self.make_profile_link,           always=False)   )
        ret.append( util.Step(self.merge_packages,              always=False)   )
        ret.append( util.Step(self.target_merge_busybox,        always=False)   )
        if len(self.files) == 1:
            ret.append( util.Step(self.target_merge_packages,   always=False)   )
            ret.append( util.Step(self.copy_libs,               always=False)   )
        else:
            ret.append( util.Step(self.copy_files,              always=False)   )
        ret.append( util.Step(self.install_modules,             always=False)   )
        ret.append( util.Step(self.update_init,                 always=False)   )
        if self.kernel:
            ret.append( util.Step(self.merge_kernel,            always=False)   )
        ret.append( util.Step(self.remove_sources,              always=False)   )
        ret.append( util.Step(self.clean_root,                  always=True)    )
        ret.append( util.Step(self.pack,                        always=False)   )
        ret.append( util.Step(self.finish_sources,              always=False)   )
        ret.append( util.Step(self.final_report,                always=True)    )
        return ret

    def install_sources(self):
        emb_root    = self.target_root
        libpath     = util.Path('/lib')
        if self.seed:
            super(EmbeddedStage, self).install_sources()
            emb_root = emb_root.pjoin(self.target_root)
            libpath = self.target_root.pjoin(libpath)
        else:
            for src in self.sources:
                src.install( root = util.Path('/') )

        for src in self.stage_sources:
            src.install( root = emb_root )
           
        for t in ('/lib', '/usr/lib'):
            linkname = emb_root.pjoin(t)
            target_path = os.path.join(os.path.dirname(linkname), os.readlink(libpath))

            if os.path.lexists(linkname):
                os.unlink(linkname)
            if os.path.islink( libpath ):
                util.mkdir(target_path)
                util.mkdir(os.path.dirname(linkname))
                os.symlink(os.readlink(libpath), linkname)

    def make_profile_link(self):
        if self.seed:
            super(EmbeddedStage, self).make_profile_link()
        else:
            targ = self.portage_cr.pjoin('/etc/make.profile')
            util.mkdir( os.path.dirname(targ) )
            if os.path.lexists(targ):
                os.unlink(targ)
            os.symlink(self.env['PORTDIR'] + '/profiles/%s' % self.profile, targ)

    def merge_packages(self):
        cmdline = '%s/inhibitor-run.sh run_emerge --newuse %s' % (
            self.env['INHIBITOR_SCRIPT_ROOT'], ' '.join(self.package_list))

        if self.seed:
            util.chroot(
                path        = self.target_root,
                function    = util.cmd,
                fargs       = {'cmdline':cmdline, 'env':self.env},
                failuref    = self.chroot_failure
            )
        else:
            util.cmd( cmdline, env = self.env )

    def target_merge_busybox(self):
        env = {}
        use = ''
        if 'USE' in self.env:
            use = self.env['USE']

        if len(self.package_list) == 0:
            use += ' static'
        use += ' make-symlinks'
        env.update(self.env)
        env['USE'] = use 
        env['ROOT'] = self.target_root

        cmdline = '%s/inhibitor-run.sh run_emerge --newuse --nodeps sys-apps/busybox' \
                % self.env['INHIBITOR_SCRIPT_ROOT']
      
        if self.seed:
            util.chroot(
                path        = self.target_root,
                function    = util.cmd,
                fargs       = {'cmdline':cmdline, 'env':env},
                failuref    = self.chroot_failure
            )
            util.chroot(
                path        = self.target_root,
                function    = self.path_sync_callback,
                fargs       = {'src':'/bin/busybox', '_':None},
                failuref    = self.chroot_failure
            )
 
        else:
            util.cmd( cmdline, env = env )
            self.path_sync_callback('/bin/busybox', None)

    def target_merge_packages(self):
        env = {}
        env.update(self.env)
        env['ROOT'] = self.target_root

        cmdline =  '%s/inhibitor-run.sh run_emerge --newuse --nodeps %s' % (
                self.env['INHIBITOR_SCRIPT_ROOT'], ' '.join(self.package_list))

        if self.seed:
            util.chroot(
                path        = self.target_root,
                function    = util.cmd,
                fargs       = {'cmdline':cmdline, 'env':env},
                failuref    = self.chroot_failure
            )
        else:
            util.cmd( cmdline, env = env )

    def _ldlibs(self, binp):
        if binp in self.checked_ldd:
            return []
        self.checked_ldd.append(binp)
            
        cmdline = 'ldd %s' % (binp,)

        rc, output = util.cmd_out( cmdline, raise_exception=False)

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
                libs.append( lib )
                util.dbg("Adding required library %s" % lib)
        return libs

    def path_sync_callback(self, src, _):
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
                self.target_root.pjoin(needed_lib),
                file_copy_callback = self.path_sync_callback
            )

    def copy_files(self):
        for min_path in self.files:
            if '*' in min_path:
                files = glob.glob( min_path )
            else:
                files = [ min_path ]

            for path in files:
                if self.seed:
                    if not os.path.lexists(self.target_root.pjoin(path)):
                        util.warn('Path %s does not exist' % (min_path,))
                        continue
                    util.chroot(
                        path        = self.target_root,
                        function    = util.path_sync,
                        fargs       = {
                            'src':                  path,
                            'targ':                 self.target_root.pjoin(path),
                            'file_copy_callback':   self.path_sync_callback
                        },
                        failuref    = self.chroot_failure
                    )
                else:
                    if not os.path.lexists(path):
                        util.warn('Path %s does not exist' % (min_path,))
                        continue
                    util.path_sync(
                        path,
                        self.target_root.pjoin(path),
                        file_copy_callback = self.path_sync_callback
                    )

    def copy_libs(self):
        for root, _, files in os.walk(self.target_root):
            for f in files:
                src_path = os.path.join( root.replace(self.target_root, ''), f )
                if self.seed:
                    util.chroot(
                        path        = self.target_root,
                        function    = self.path_sync_callback,
                        fargs       = {'src':src_path, '_':None},
                        failuref    = self.chroot_failure
                    )
                else:
                    self.path_sync_callback( src_path, None )

    def install_modules(self):
        emb_root = self.target_root
        if self.seed:
            emb_root = emb_root.pjoin(self.target_root)

        for d in 'init.d', 'conf.d':
            util.mkdir(emb_root.pjoin('etc/%s' % (d,)))

        for m in self.modules:
            init = self.moduledir.pjoin('%s.init' % m)
            conf = self.moduledir.pjoin('%s.conf' % m)
            if os.path.exists(init):
                shutil.copy2(init, emb_root.pjoin('etc/init.d/%s' % m))
            if os.path.exists(conf):
                shutil.copy2(conf, emb_root.pjoin('etc/conf.d/%s' % m))

    def update_init(self):
        emb_root = self.target_root
        if self.seed:
            emb_root = emb_root.pjoin(self.target_root)

        for initd in glob.iglob('%s/*' % emb_root.pjoin('etc/init.d')):
            int_path = initd.replace(emb_root, '')
            util.dbg('Adding %s to init' % int_path)
            util.chroot(
                path        = emb_root,
                function    = util.cmd,
                fargs       = {
                    'cmdline':  '%s enable' % int_path,
                    'shell':    '/bin/ash'
                },
                failuref    = self.chroot_failure,
            )

    def merge_kernel(self):
        args = ['--build_name', self.build_name,
            '--kernel_pkg', '\'%s\'' % (self.kernel.kernel_pkg,)]

        cmdline = '%s/kernel.sh %s' % (
            self.env['INHIBITOR_SCRIPT_ROOT'],
            ' '.join(args) )

        env = {}
        env.update(self.env)
        env['ROOT'] = '/tmp/inhibitor/kernelbuild'

        if self.seed:
            util.mkdir( self.target_root.pjoin(env['ROOT']) )
            util.chroot(
                path        = self.target_root,
                function    = util.cmd,
                fargs       = {'cmdline':cmdline, 'env':env},
                failuref    = self.chroot_failure,
            )
        else:
            util.cmd( cmdline, env )

    def remove_sources(self):
        super(EmbeddedStage, self).remove_sources()
        for src in self.stage_sources:
            src.remove()

    def clean_root(self):
        emb_root = self.target_root
        if self.seed:
            emb_root = emb_root.pjoin(self.target_root)
        rm_dirs = [
            '/var/cache/edb',   # Portage
            '/var/lib/portage', # Portage
            '/var/db/pkg',      # Portage
            '/usr/share',       # Busybox emerge.
            '/etc/portage',     # Busybox emerge.
            '/lib/rcscripts',   # Busybox emerge
        ]
        
        for d in rm_dirs:
            if os.path.isdir( emb_root.pjoin(d) ):
                shutil.rmtree( emb_root.pjoin(d) )

    def pack(self):
        emb_root = self.target_root
        if self.seed:
            emb_root = emb_root.pjoin(self.target_root)

        basedir = util.Path( os.path.dirname(self.tarpath) )
        util.mkdir(basedir)

        archive = tarfile.open(self.tarpath, 'w:bz2')
        archive.add(emb_root,
            arcname = '/',
            recursive = True
        )
        archive.close()

        curdir = os.path.realpath(os.curdir)
        os.chdir(emb_root)
        util.cmd('find ./ | cpio -H newc -o | gzip -c -9 > %s' % (self.cpiopath))
        os.chdir(curdir)

        if self.kernel:
            r = util.Path('/')
            if self.seed:
                r = self.target_root
            r = r.pjoin('/tmp/inhibitor/kernelbuild')

            kernel_link = r.pjoin('/boot/kernel')
            kernel_path = os.path.realpath( kernel_link )
            
            if os.path.lexists( basedir.pjoin('kernel') ):
                os.unlink(basedir.pjoin('kernel'))

            shutil.copy2(kernel_path, basedir.pjoin( os.path.basename(kernel_path) ))
            os.symlink(os.path.basename(kernel_path), basedir.pjoin('kernel'))

    def finish_sources(self):
        super(EmbeddedStage, self).finish_sources()
        for src in self.stage_sources:
            src.finish()

    def final_report(self):
        util.info("Created %s" % (self.tarpath,))
        util.info("Created %s" % (self.cpiopath,))
        if self.conf.has('kernel'):
            util.info("Kernel copied into %s" % (os.path.dirname(self.tarpath),) )

