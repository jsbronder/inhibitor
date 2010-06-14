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
    def __init__(self, stage_conf, build_name, **keywds):
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
        if self.conf.has('fs_add'):
            self.conf.fs_add.keep = True
            self.conf.fs_add.dest = util.Path('/')
            self.stage_sources.append(self.conf.fs_add)

        baselayout     = source.create_source(
            src = 'file://%s/sh/early-userspace/root' % inhibitor_state.paths.share,
            keep = True,
            dest = util.Path('/')
        )
        self.stage_sources.append(baselayout)

        for src in self.stage_sources:
            src.post_conf(inhibitor_state)
            src.init()

        super(EmbeddedStage, self).post_conf(inhibitor_state)
        self.moduledir      = self.istate.paths.share.pjoin('sh/early-userspace/modules')
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
        ret.append( util.Step(self.install_sources,             always=False)   )
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
        ret.append( util.Step(self.remove_sources,              always=False)   )
        ret.append( util.Step(self.pack,                        always=False)   )
        ret.append( util.Step(self.clean_sources,               always=False)   )
        ret.append( util.Step(self.final_report,                always=True)    )
        return ret

    def make_profile_link(self):
        targ = self.portage_cr.pjoin('/etc/make.profile')
        util.mkdir( os.path.dirname(targ) )
        if os.path.lexists(targ):
            os.unlink(targ)
        os.symlink(self.env['PORTDIR'] + '/profiles/%s' % self.profile, targ)

    def merge_packages(self): 
        util.cmd(
            '%s/inhibitor-run.sh run_emerge --newuse %s'
                % (self.env['INHIBITOR_SCRIPT_ROOT'], ' '.join(self.package_list)),
            env = self.env
        )

    def install_sources(self):
        for src in self.sources:
            src.install( root = util.Path('/') )
        for src in self.stage_sources:
            src.install( root = self.target_root )
        libpath = '/lib'
        target = self.target_root.pjoin(libpath)
        if os.path.lexists( target ):
            os.unlink( target )
        if os.path.islink( libpath ):
            os.symlink(os.readlink(libpath), target)
            util.mkdir( self.target_root.pjoin( os.path.realpath(libpath) ) )
    
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
       
        util.cmd(
            '%s/inhibitor-run.sh run_emerge --newuse --nodeps sys-apps/busybox'
                % self.env['INHIBITOR_SCRIPT_ROOT'],
            env = env
        )

    def target_merge_packages(self):
        env = {}
        env.update(self.env)
        env['ROOT'] = self.target_root
        util.cmd(
            '%s/inhibitor-run.sh run_emerge --newuse --nodeps %s'
                % (self.env['INHIBITOR_SCRIPT_ROOT'], ' '.join(self.package_list)),
            env = env
        )

    def _ldlibs(self, binp):
        if binp in self.checked_ldd:
            return []
        self.checked_ldd.append(binp)

        rc, output = util.cmd_out(
            cmdline         = 'ldd %s' % (binp,),
            raise_exception =   False,
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
                files = glob.glob(min_path)
            else:
                files = [ min_path ]

            for path in files:
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
                root_path = os.path.join( root.replace(self.target_root, ''), f )
                self.path_sync_callback( root_path, None )

    def install_modules(self):
        for m in self.modules:
            init = self.moduledir.pjoin('%s.init' % m)
            conf = self.moduledir.pjoin('%s.conf' % m)
            if os.path.exists(init):
                shutil.copy2(init, self.target_root.pjoin('etc/init.d/%s' % m))
            if os.path.exists(conf):
                shutil.copy2(conf, self.target_root.pjoin('etc/conf.d/%s' % m))

    def update_init(self):
        for initd in glob.iglob('%s/*' % self.target_root.pjoin('etc/init.d')):
            int_path = initd.replace(self.target_root, '')
            util.dbg('Adding %s to init' % int_path)
            util.chroot(
                path = self.target_root,
                function = util.cmd,
                fargs = {
                    'cmdline':  '%s enable' % int_path,
                    'shell':    '/bin/ash'
                },
                failuref = self.chroot_failure,
            )

    def remove_sources(self):
        super(EmbeddedStage, self).remove_sources()
        for src in self.stage_sources:
            src.remove()

    def pack(self):
        basedir = os.path.dirname(self.tarpath)
        util.mkdir(basedir)

        archive = tarfile.open(self.tarpath, 'w:bz2')
        archive.add(self.target_root,
            arcname = '/',
            recursive = True
        )
        archive.close()

        curdir = os.path.realpath(os.curdir)
        os.chdir(self.target_root)
        util.cmd('find ./ | cpio -H newc -o | gzip -c -9 > %s' % (self.cpiopath))
        os.chdir(curdir)

    def clean_sources(self):
        super(EmbeddedStage, self).clean_sources()
        for src in self.stage_sources:
            src.finish()

    def final_report(self):
        util.info("Created %s" % (self.tarpath,))
        util.info("Created %s" % (self.cpiopath,))
        if self.conf.has('kernel'):
            util.info("Kernel copied into %s" % (os.path.dirname(self.tarpath),) )
