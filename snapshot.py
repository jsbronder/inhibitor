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

    def __init__(self, name, **keywords):
        self.name = name

        settings_conf = {
            'snapshot': {
                'required_keys':    ['repo_type',   'src',          'type'],
                'valid_keys':       ['rev',         'repo_dir',     'snapfile',
                                    'repodir'],
                'config_init':      {'name':name}
            }
        }

        super(InhibitorSnapshot, self).__init__(
            settings_conf=settings_conf,
            **keywords)
       
        self.expand_snapshot_settings(**keywords)
        self.sanity(['snapshot'])


    def expand_snapshot_settings(self, **keywords):
        s = self.snapshot
        s['repodir']    = path_join(self.base['repo_cache'], name ) + '/'
        
        for k in ['src', 'repo_type', 'rev', 'snapfile']:
            if k in keywords:
                s[k] = keywords[k]

        if 'rev' in s:
            s['snapfile'] = path_join(self.base['snapshots'], '%s-%s.tar.bz2'
                % (self.name, self.rev))
        else:
            s['snapfile'] = 'unknown/until/we/get/a/revision'

        if not self.snapshot['repo_type'] in ['git']:
            raise InhibitorError(
                'Unknown snapshot src repo_type:  \'%s\'' % self.snapshot['src'])

        self.myenv = {}
        if 'repo_type' in s and s['repo_type'] == 'git':
            self.myenv = {'GIT_DIR':path_join(self.snapshot['repodir'], '.git')}

    def is_overlay(self):
        return self.snapshot['type'] == 'overlay'

    def cachedir(self):
        return path_join(
            self.base['snapshot_cache'],
            '%s-%s' % (self.name, self.rev),
            'tree')
        
    def current_cache(self):
        if not self.rev or not self.snapshot['snapfile']:
            return False
       
        if os.path.exists(self.snapshot['snapfile']) \
            and os.path.isdir(self.cachedir()) \
            and os.listdir(self.cachedir()):
            return True

    def run(self):
        self.update_repo()
        self.parse_rev()
        self.create_snapfile()
        self.create_cachedir()


    def update_repo(self):
        if self.snapshot['repo_type'] == 'git':
            check_dir = self.myenv['GIT_DIR']
            update_cmd = 'git pull'
            create_cmd = 'git clone %s %s' % (self.snapshot['src'], self.snapshot['repodir'])

        
        if not os.path.isdir( check_dir ):
            if os.path.exists(self.snapshot['repodir']):
                warn('%s is not a %s repository.'
                    % ( self.snapshot['repodir'], self.snapshot['repo_type'])
                if self.base['force']:
                    warn('Removing...')
                    try:
                        shutil.rmtree(self.snapshot['repodir'])
                    except OSError, e:
                        InhibitorError('Cannot clean directory: %s' % e)
                else:
                    raise InhibitorError('%s exists and force=False'
                        % self.snapshot['repodir'])
            cmd(create_cmd, env=self.myenv)
        else:
            cmd(update_cmd, env=self.myenv)

    def parse_rev(self):
        if not 'rev' in self.snapshot:
            if self.snapshot['repo_type'] == 'git':
                self.rev = file_getline( path_join(
                    self.snapshot['repodir'],
                    '.git', 'refs', 'heads', 'master'))
                self.rev = self.rev[:7]

        if self.snapshot['snapfile'].startswith('unknown/'):
            self.snapshot['snapfile'] = path_join(
                self.base['snapshots'],
                    '%s-%s.tar.bz2' % (self.name, self.rev))

    def create_snapfile(self):
        if not self.base['force'] and self.current_cache():
            info('Skipping archive step, %s already exists'
                % os.path.basename(self.snapshot['snapfile']))
            return

        if os.path.exists(self.snapshot['snapfile']):
            try:
                os.unlink(self.snapshot['snapfile'])
            except OSError, e:
                raise InhibitorError("Failed to remove %s: %s"
                    % (self.snapshot['snapfile'], e))
               
        if self.snapshot['repo_type'] == 'git':
            do = 'git archive --format=tar --prefix=tree/ %s | bzip2 --fast -f > %s' \
                % (self.rev, self.snapshot['snapfile'])

        cmd(do, env=self.myenv)
        md5_hash = get_checksum(self.snapshot['snapfile'])
        write_hashfile(self.base['snapshots'],
            self.snapshot['snapfile'],
            {'md5':md5_hash}
        )



    def create_cachedir(self):
        base_dir = path_join(
            self.base['snapshot_cache'],
            '%s-%s' % (self.name, self.rev)
        )
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        
        os.makedirs(base_dir)
        cmd('tar -xjpf %s -C %s/' % (self.snapshot['snapfile'], base_dir))


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
            args['src'] = a
        elif o in ('-t', '--repo'):
            args['repo_type'] = a
        elif o in ('-r', '--rev'):
            args['rev'] = a
        elif o in ('-f', '--force'):
            args['force'] = True
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





