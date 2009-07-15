import glob
import shutil

from base_funcs import *
from base import InhibitorObject
from snapshot import InhibitorSnapshot

class InhibitorStage(InhibitorObject):
    def __init__(self,
        name,
        config_init={},
        cmdline={},
        actions={},
        **keywords):

        self.name = name

        config_init = config_init
        config_init['name'] = name

        settings_conf = {
            'stage':    {
                'required_keys':    ['snapshot',    'profile',          'arch',
                                    'make_conf',     'run_cmdline'  ],
                'valid_keys':       ['overlays',    'portage_conf',     
                                    'seed',         'clean',
                                    'stage_scripts','stage_config',     'package_cache' ],
                'config_init':      config_init,
            }
        }
        
        if len(actions) == 0:
            actions = {
                'create':   ['create_dirs', 'unpack_seed',     'get_snapshots',        'write_confdir',
                            'write_make_conf',  'files_to_chroot',
                            'bind_mounts',      'setup_profile',
                            'unbind_mounts',    'clean',                'pack']
            }
        
        super(InhibitorStage, self).__init__(
            settings_conf=settings_conf,
            cmdline=cmdline,
            actions=actions,
            **keywords)
       
        self.init_vars()

    def _kill_chroot_pids(self):
        for root in glob.glob('/proc/[0-9][0-9]*/root'):
            if os.readlink(root).startswith(self.builddir):
                pid = root[len('/proc/'):-len('/root')]
                warn('Killing chroot pid %s' % pid)
                _kill_pids([pid])

    def init_vars(self):
        """
        Needs seed.
        """
        self.seed       = path_join(self.base['builds'], self.stage['seed'] + '.tar.bz2')
        self.seed_cache = path_join(self.base['stage_cache'], self.stage['seed'])
        self.builddir   = path_join(self.base['stage_cache'], self.name)
        self.tarfile    = path_join(self.base['builds'], self.name + '.tar.bz2')
        self.snapshots  = [self.stage['snapshot']]
        if self.stage['overlays']:
            self.snapshots.extend(self.stage['overlays'])

        if 'package_cache' in self.stage:
            self.pkgcache = self.stage['package_cache']
        else:
            self.pkgcache = path_join(self.base['packages'], self.name)
        
        cleanable = ['/tmp', '/var/tmp/']
        if not 'clean' in self.stage:
            self.stage['clean'] = cleanable
        else:
            self.stage['clean'].extend(cleanable)


        self.mounts = {
            '/proc':        {},
            '/dev':         {},
            '/sys':         {},
            self.pkgcache:  {'dest':'/tmp/inhibitor/packages'}
        }

        self.copy_files = {
            '/etc/hosts':               {},
            '/etc/resolv.conf':         {},
            'inhibitor-functions.sh':   {'dest':'/tmp/inhibitor/'},
            'inhibitor-run.sh':         {
                'dest':     '/tmp/inhibitor/',
                'mode':     0755 }

        }

    def create_dirs(self):
        # Don't worry, it'll be extended in the future :)
        for d in [ self.pkgcache ]:
            if not os.path.exists(d):
                os.makedirs(d)


    def unpack_seed(self):
        if os.path.exists(self.builddir):
            if self.base['force']:
                info('Build directory exists, forcing removal.')
                shutil.rmtree(self.builddir)
            else:
                warn('Build directory exists, but force is disabled.  Leaving it as is.')

        if not os.path.exists(self.builddir):
            os.makedirs(self.builddir)

        if os.path.exists(self.seed_cache) and os.listdir(self.seed_cache):
            info('Using cached seed for %s', os.path.basename(self.seed_cache))
            cmd('rsync -a --delete %s/ %s/'
                % (self.seed_cache, self.builddir) )
        else:
            info('Using packed seed for %s' % os.path.basename(self.seed_cache))
            cmd('tar -xjpf %s -C %s/'
                % (self.seed, self.builddir))
    
    def get_snapshots(self):
        override = {'base':self.base}

        for snap_def in self.snapshots:
            snapshot = InhibitorSnapshot(
                snap_def[0],
                rev=snap_def[1],
                config_file=self.config_file,
                settings_override=override,
                quiet=True)

            if snapshot.current_cache():
                info('Using cached copy of %s' % '-'.join(snap_def))
            else:
                info('Creating snapshot of %s' % '-'.join(snap_def))
                snapshot.run()

    def write_confdir(self):
        bd = path_join(self.builddir, 'etc', 'portage')
        if not os.path.exists(bd):
            os.makedirs(bd)

        for path, contents in self.stage['portage_conf'].items():
            try:
                dest = path_join(bd, path)
                dest_dir = os.path.dirname(dest)
                
                if os.path.exists(dest):
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    else:
                        os.unlink(dest)

                if not os.path.isdir(dest_dir):
                    if os.path.exists(dest_dir):
                        shutil.rmtree(dest_dir)
                    os.makedirs(dest_dir)

                fd = open(dest, 'w')
                fd.write(contents)
                fd.close()
            except (IOError, OSError), e:
                raise InhibitorError('Failed to write %s: %s' 
                    % (path_join(bd, path), e))

    def write_make_conf(self):
        f = path_join(self.builddir, 'etc', 'make.conf')
        try:
            fd = open(f, 'w')
            fd.write(self.stage['make_conf'])
            fd.close()
        except (IOError, OSError), e:
            raise InhibitorError('Failed to write %s: %s'
                % (f, e))

    def setup_profile(self):
        if self.stage['profile'].startswith('/'):
            raise InhibitorError('Invalid profile string: %s' % self.stage['profile'])
            
        targ = path_join('..', 'usr', 'portage', 'profiles', self.stage['profile'])
        chk = path_join(self.builddir, 'usr', 'portage', 'profiles', self.stage['profile'])
        mk_profile = path_join(self.builddir, 'etc', 'make.profile')


        if not os.path.exists(chk):
            raise InhibitorError('Profile %s does not exist.' % self.stage['profile'])

        if os.path.exists(mk_profile):
            os.unlink(mk_profile)
        os.symlink(targ, path_join(self.builddir, 'etc', 'make.profile') )

    def files_to_chroot(self):
        for f, info in self.copy_files.items():
            if f.startswith('/'):
                src = f
            else:
                src = path_join(self.base['installdir'], f)

            if 'dest' in info:
                dest = path_join(self.builddir, info['dest'])
                if info['dest'].endswith('/'):
                    dest = path_join(dest, f)
            elif f.startswith('/'):
                # path_join doesn't like leading /'s
                dest = path_join(self.builddir, f[1:])
            else:
                dest = path_join(self.builddir, 'tmp', 'inhibitor', f)

            if not os.path.exists(os.path.dirname(dest)):
                os.makedirs(os.path.dirname(dest))
            
            shutil.copy(src, dest)


    def setup_chroot(self):
        # TODO:  Parse the files we write.
        #   - Rip leading whitespace out due to python strings.
        #   - Insert variables metro style. $[[stage/run_script]]

        write_files = []

        if 'stage_scripts' in self.stage:
            for f in self.stage['stage_scripts']:
                write_files.append( (self.stage['stage_scripts'][f], f, 0755) )

        if 'stage_config' in self.stage:
            for f in self.stage['stage_config']:
                write_files.append( (self.stage['stage_config'][f], f, 0644) )

        for contents, filename, perms in write_files:
            f = path_join(self.builddir, 'tmp', filename)
            try:
                f.open(f, 'w')
                f.write(contents)
                f.close()
                os.chmod(f, perms)
            except (OSError, IOError), e:
                raise InhibitorException('Failed to write %s to the chroot: %s'
                    % (filename, e) )

    def bind_mounts(self):
        overlay_cnt = 1
        override = {'base':self.base}

        for snap_def in self.snapshots:
            snapshot = InhibitorSnapshot(
                snap_def[0],
                rev=snap_def[1],
                config_file=self.config_file,
                settings_override=override,
                quiet=True)

            if snapshot.is_overlay():
                self.mounts[snapshot.cachedir()] = {'dest':'/usr/local/overlay-%d' % overlay_cnt}
                overlay_cnt += 1
            else:
                if '/usr/portage' in self.mounts.values():
                    raise InhibitorError('More then one portage snapshot specified.')
                self.mounts[snapshot.cachedir()] = {'dest':'/usr/portage'}

        # Shorter path means we should mount first.
        # At least, in practice, that'll usually work.
        mount_order = sorted(self.mounts.keys())
        for m in mount_order:
            dest = m
            if 'dest' in self.mounts[m]:
                dest = self.mounts[m]['dest']

            full_dest = path_join(self.builddir, dest)
            
            if not os.path.exists(full_dest):
                os.makedirs(full_dest)
                self.stage['clean'].append(dest)
            cmd('mount -o bind %s %s' % (m, path_join(self.builddir, dest)) )


    def run_in_chroot(self):
        cmd('chroot %s /tmp/inhibitor/inhibitor-run.sh %s'
            % (self.builddir, self.run_cmdline) )

   
    def unbind_mounts(self):
        unmount_order = []
        for k,v in self.mounts.items():
            if 'dest' in v:
                unmount_order.append(path_join(self.builddir, v['dest']))
            else:
                unmount_order.append(path_join(self.builddir, k))

        unmount_order.reverse()
        failed = False
        for mp in unmount_order:
            if cmd('umount %s' % mp, raise_exception=False) != 0:
                warn('Unmount of %s failed' % mp)
                warn('Killing any processes still running in the chroot')

                if cmd('umount %s' % mp, raise_exception=False) != 0:
                    failed = True
                    err('Could not umount %s' % mp)

        if failed:
            raise CatalystError('Some chroot mountpoints could not be umounted.')

    def clean(self):
        if 'clean' in self.stage:
            for x in self.stage['clean']:
                path = x

                if not x.startswith(self.builddir):
                    path = path_join(self.builddir, x)

                if not os.path.exists(path):
                    continue

                if not os.path.isdir(path):
                    os.unlink(path)
                else:
                    shutil.rmtree(path)

    def pack(self):
        cmd('tar -cjpf %s -C %s ./' % (self.tarfile, self.builddir))


class InhibitorStageOne(InhibitorStage):
    def __init__(self, name, **keywords):
        if not name.startswith('stage1-'):
            name = 'stage1-' + name
        super(InhibitorStageOne, self).__init__(name, 
            config_init={'stage':'stage1'},
            run_cmdline='run_stage1',
            **keywords)
