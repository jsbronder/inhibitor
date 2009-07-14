import os
import os.path
import shutil

from base_funcs import *
from base import InhibitorObject

class InhibitorSnapshot(InhibitorObject):
    """
    Manage a single snapshot such that catalyst will be happy with it.

    TODO:
        - support git branches
        - repos aside from git (rsync, then svn probably)
    """

    def __init__(self, name, rev=None, **keywords):
        self.name = name

        settings_conf = {
            'snapshot': {
                'required_keys':    ['repo_type', 'src', 'type'],
                'valid_keys':       ['rev'],
                'config_init':      {'name':name}
            }
        }

        super(InhibitorSnapshot, self).__init__(
            settings_conf=settings_conf,
            **keywords)
        
        self.repodir        = path_join(self.base['repo_cache'], name ) + '/'
        self.snapdir        = self.base['snapshots']
        self.src            = self.snapshot['src']
        self.type           = self.snapshot['type']
        self.repo_type      = self.snapshot['repo_type']
        self.force          = 'force' in self.base and self.base['force'] or False
        self.rev            = rev
        self.snapfile       = None

        if not self.rev and 'rev' in self.snapshot['rev']:
            self.rev = self.snapshot['rev']

        if self.rev:
            self.snapfile = path_join(self.snapdir, '%s-%s.tar.bz2'
                % (self.name, self.rev))


        if not self.repo_type in ['git']:
            raise InhibitorError('Unknown snapshot src repo_type:  \'%s\'' % self.src)

    def is_overlay(self):
        return self.snapshot['type'] == 'overlay'

    def cachedir(self):
        return path_join(
            self.base['snapshot_cache'],
            '%s-%s' % (self.name, self.rev),
            'tree')
        

    def current_cache(self):
        if not self.rev or not self.snapfile:
            return False
       
        if os.path.exists(self.snapfile) \
            and os.path.isdir(self.cachedir()) \
            and os.listdir(self.cachedir()):
            return True


    def run(self):
        if self.repo_type == 'git':
            self._git_create_snapshot()

        self.create_cachedir()


    def create_cachedir(self):
        base_dir = path_join(self.base['snapshot_cache'], '%s-%s' % (self.name, self.rev) )
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        
        os.makedirs(base_dir)
        os.symlink('tree', path_join(base_dir, 'portage'))
        os.symlink('tree', path_join(base_dir, 'overlay'))

        cmd('tar -xjpf %s -C %s/' % (self.snapfile, base_dir))
        if 'catalyst_support' in self.base and self.base['catalyst_support']:
            write_hashfile(base_dir, self.snapfile, {'md5':None}, dest_filename='catalyst-hash')


    def _git_create_snapshot(self):
        myenv={'GIT_DIR':path_join(self.repodir, '.git')}

        if not os.path.isdir( myenv['GIT_DIR'] ):
            if os.path.exists(self.repodir):
                warn('%s is not a git repository.  Removing.' % self.repodir)
                try:
                    shutil.rmtree(self.repodir)
                except OSError, e:
                    InhibitorError('Cannot clean directory: %s' % e)

            cmd('git clone %s %s' % (self.src, self.repodir))
        else:
            cmd('git pull', env=myenv)

        if self.rev == None:
            self.rev = file_getline( path_join(myenv['GIT_DIR'], 'refs', 'heads', 'master') )
            self.rev = self.rev[:7]
            self.snapfile = path_join(self.snapdir, '%s-%s.tar.bz2'
                % (self.name, self.rev))

        if not self.force and self.current_cache():
            info('Skipping archive step, %s already exists' % os.path.basename(self.snapfile))
            return

        if os.path.exists(self.snapfile):
            try:
                os.unlink(self.snapfile)
            except OSError, e:
                raise InhibitorError("Failed to remove %s: %s" % (self.snapfile, e))
                
        cmd('git archive --format=tar --prefix=tree/ %s | bzip2 --fast -f > %s'
            % (self.rev, self.snapfile), env=myenv)
      
        md5_hash = get_checksum(self.snapfile)
        write_hashfile(self.snapdir, self.snapfile, {'md5':md5_hash})


if __name__ == '__main__':
    import getopt
    name        = None
    src         = None
    repo_type   = None
    rev         = None
    force       = False
    configfile  = None

    usage =  """snapshot.py [ARGUMENTS]
Creates a snapshot from a specified subversion or git repository.

REQUIRED ARGUMENTS:
    -n, --name <name>       Snapshot name
    -s, --src  <src>        Snapshot source
    -c, --config <path>     Config file path

OPTIONAL ARGUMENTS:
    -R, --repo <repo_type>  Snapshot repository type
    -r, --rev  <rev>        Revison to snapshot (default is HEAD)
    -f, --force             Force overwriting of files.
    -h, --help              This screen
"""

    try:
        sa, la = getopt.gnu_getopt(sys.argv[1:], "n:s:R:r:fhc:",
                    [   'name',
                        'source',
                        'repo_type',
                        'rev',
                        'force',
                        'help',
                        'config' ])
    except getopt.GetoptError, e:
        raise InhibitorError("Error parsing commandline: %s" % e)

    args = {}
    for o, a in sa:
        if o in ('-n', '--name'):
            name = a
        elif o in ('-s', '--source'):
            args['snapshot.src'] = a
        elif o in ('-t', '--repo'):
            args['snapshot.repo'] = a
        elif o in ('-r', '--rev'):
            args['snapshot.rev'] = a
        elif o in ('-f', '--force'):
            args['base.force'] = True
        elif o in ('-h', '--help'):
            print usage
            sys.exit(0)
        elif o in ('-c', '--config'):
            args['config_file'] = a
        else:
            import errno
            str=''
            if a:
               str = "="+a 
            raise InhibitorError("Unknown option in command line '%s'%s" % (o, str))
    if name == None:
        raise InhibitorError("name (-n) must be defined.")

    InhibitorSnapshot(name, **args).run()





