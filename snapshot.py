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
    """

    def __init__(self, name, **keywords):
        self.name = name

        required_settings = [
            ('snapshot',    ['type', 'src'], {'name':name})
        ]

        valid_settings = [
            ('snapshot',    ['rev'], {'name':name})
        ]

        super(InhibitorSnapshot, self).__init__(
            required_settings=required_settings,
            valid_settings=valid_settings,
            **keywords)
        

        self.repodir        = os.path.join(self.base['repo_cache'] + name ) + '/'
        self.snapdir        = self.base['snapshots']
        self.snapfile       = None
        self.type           = self.snapshot['type']

        if 'force' in keywords:
            self.force = True
        else:
            self.force = False
        
        if not 'rev' in self.snapshot:
            self.rev = None
        else:
            self.rev            = self.snapshot['rev']

        if not self.type in ['svn', 'git']:
            raise InhibitorError('Unknown snapshot src type:  \'%s\'' % self.src)


        for p in [self.repodir, self.snapdir]:
            if not os.path.exists(p):
                try:
                    os.makedirs(p)
                except OSError, e:
                    raise InhibitorError('Cannot create path %s : %s' % (p, e))

    def run(self):
        if self.type == 'git':
            self._git_create_snapshot()
        elif self.type == 'svn':
            self._svn_create_snapshot()

        self.create_cachedir()


    def create_cachedir(self):
        base_dir = os.path.join(self.base['snapshot_cache'], '%s-%s' % (self.name, self.rev) )
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        
        os.makedirs(base_dir)
        os.symlink('overlay', os.path.join(base_dir, 'portage'))

        cmd('tar -xjpf %s -C %s/' % (self.snapfile, base_dir))
        if 'catalyst_support' in self.base and self.base['catalyst_support']:
            write_hashfile(base_dir, self.snapfile, {'md5':None}, dest_filename='catalyst-hash')


    def _git_create_snapshot(self):
        myenv={'GIT_DIR':os.path.join(self.repodir, '.git')}

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
            self.rev = file_getline( os.path.join(myenv['GIT_DIR'], 'refs', 'heads', 'master') )
            self.rev = self.rev[:7]

        self.snapfile = os.path.join(self.snapdir, '%s-%s.tar.bz2'
            % (self.name, self.rev))

        if not self.force and os.path.exists( self.snapfile ):
            info('Skipping archive step, %s already exists' % os.path.basename(self.snapfile))
            return

        if os.path.exists(self.snapfile):
            try:
                os.unlink(self.snapfile)
            except OSError, e:
                raise InhibitorError("Failed to remove %s: %s" % (self.snapfile, e))
                
        cmd('git archive --format=tar --prefix=overlay/ %s | bzip2 --fast -f > %s'
            % (self.rev, self.snapfile), env=myenv)
      
        md5_hash = get_checksum(self.snapfile)
        write_hashfile(self.snapdir, self.snapfile, {'md5':md5_hash})


    def _svn_create_snapshot(self):
        svndir = os.path.join(self.repodir, '.svn')
        if not os.path.isdir(svndir):
            if os.path.exists(self.repodir):
                warn('%s is not a svn repository.  Removing.' % self.repodir)
                try:
                    shutil.rmtree(self.repodir)
                except OSError, e:
                    InhibitorError('Cannot clean directory: %s' %e)
            cmd('svn checkout %s %s' % (self.src, self.repodir))    

        if self.rev == None:
            cmd('svn up %s' % (self.repodir))
            self.rev = cmd_out("svn info %s | awk '/Revision/{print $2}'" % self.repodir)
            self.rev = 'r' + self.rev
        else:
            if self.rev[0] != 'r':
                self.rev = 'r' + self.rev
            cmd('svn up -%s %s' % (self.rev, self.repodir))

        self.snapfile = os.path.join(self.snapdir, '%s-%s.tar.bz2'
            % (self.name, self.rev))

        if not self.force and os.path.exists( self.snapfile ):
            info('Skipping archive step, %s already exists' % os.path.basename(self.snapfile))
            return
 
        cmd("cd %s;tar -cjf %s --exclude='.svn' --transform='s,^,overlay/,' ./"
            % (self.repodir, self.snapfile) )


if __name__ == '__main__':
    import getopt
    name        = None
    src         = None
    type        = None
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
    -t, --type <type>       Snapshot type
    -r, --rev  <rev>        Revison to snapshot (default is HEAD)
    -f, --force             Force overwriting of files.
    -h, --help              This screen
"""

    try:
        sa, la = getopt.gnu_getopt(sys.argv[1:], "n:s:t:r:fhc:",
                    [   'name',
                        'source',
                        'type',
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
        elif o in ('-t', '--type'):
            args['type'] = a
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





