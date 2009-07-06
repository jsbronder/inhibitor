import os
import os.path
import shutil

from base_funcs import *
from base import InhibitorObject

class InhibitorSnapshot(InhibitorObject):
    """
    Manage a single snapshot such that catalyst will be happy with it.
    """

    def __init__(self, name, src=None, type=None, rev=None, force=False, **keywords):
        super(InhibitorSnapshot, self).__init__(**keywords)
        self.name   = name
        self.src    = src
        self.rev    = rev
        self.force  = force
        self.type   = type
        self.repodir        = os.path.join(self.settings['base']['repo_cache'] + name ) + '/'
        self.snapdir        = self.settings['base']['snapshots']
        self.snapfile       = None

        if catalyst_support:
            self.catalyst_snapcache = self.settings['base']['snapshot_cache']
            self.catalyst_snapshots = self.settings['base']['snapshots']
        else:
            self.catalyst_snapcache = None
            self.catalyst_snapshots = None
             
     
        if self.src == None:
            try:
                self.src = self.settings['snapshot'][self.name]['src']
            except KeyError:
                raise InhibitorError('Source for snapshot %s is undefined' % self.name)
             
        if self.type == None:
            try:
                self.type = self.settings['snapshot'][self.name]['type']
            except KeyError:
                if self.src.startswith('git://'):
                    self.type = 'git'
                elif self.src.startswith('svn://'):
                    self.type = 'svn'
                else:
                    raise InhibitorError('Unable to parse upstream repository type for snapshot %s'
                        % self.name)

        if not self.type in ['svn', 'git']:
            raise InhibitorError('Unknown snapshot src type:  \'%s\'' % self.src)


        for p in [self.repodir, self.snapdir, 
            self.catalyst_snapshots, self.catalyst_snapcache]:
            if p == None:
                continue
            if not os.path.exists(p):
                try:
                    os.makedirs(p)
                except OSError, e:
                    raise InhibitorError('Cannot create path %s : ' % (p, e))

    def run(self):
        if self.type == 'git':
            self._git_create_snapshot()
        elif self.type == 'svn':
            self._svn_create_snapshot()

        if catalyst_support:
            self.catalyst_snapshot()


    def catalyst_snapshot(self):
        # Make a snapshot_cache that catalyst can handle.
        # We don't know if this is portage or an overlay, so we symlink the dirs.
        info('Creating catalyst-supporting layout.')
        base_dir = os.path.join(self.catalyst_snapcache, '%s-%s' % (self.name, self.rev) )
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        
        os.makedirs(base_dir)
        os.symlink('overlay', os.path.join(base_dir, 'portage'))

        cmd('tar -xjpf %s -C %s/' % (self.snapfile, base_dir))
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
        print "Error parsing commandline: %s" % e

    for o, a in sa:
        if o in ('-n', '--name'):
            name = a
        elif o in ('-s', '--source'):
            src = a
        elif o in ('-t', '--type'):
            type = a
        elif o in ('-r', '--rev'):
            rev = a
        elif o in ('-f', '--force'):
            force = True
        elif o in ('-h', '--help'):
            print usage
            sys.exit(0)
        elif o in ('-c', '--config'):
            configfile = a
        else:
            import errno
            str=''
            if a:
               str = "="+a 
            raise InhibitorError("Unknown option in command line '%s'%s" % (o, str))
    if name == None or (src == None and configfile == None):
        raise InhibitorError("Both name (-n) and source (-s) must be defined.")

    InhibitorSnapshot(name, src, type=type, rev=rev, force=force, settings_file=configfile).run()





