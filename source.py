import shutil
import os
import tarfile

from util import *


class InhibitorSource(object):
    """
    Base class for source objects.

    @param src                  - Source path.
    @param dest                 - Destination within the stage4 chroot.
    @param name                 - Unique identifier for this source object.  If
                                  set to none, this is parsed out of the src dependent
                                  upon type.
    @param keep                 - Leave output in the stage4 build.
    @param rev                  - Revision of the source to use.  See
                                  _GitSource.
    """
    def __init__(self, src, dest = None, name = None, keep = False, **keywds):
        self.istate     = None
        self.src        = src
        self.dest       = dest
        self.name       = name
        self.keep       = keep
        self.keywds     = keywds
        self.backend    = None

    def _check(self):
        if not self.istate:
            raise InhibitorError(
                "post_conf() not yet called for InhibitorSource %s" % self.name)
    
    def _init_backend(self):
        if type(self.src) == types.StringType:
            if self.src.startswith("git://"):
                if self.name == None:
                    self.name = self.src.split('/')[-1].rstrip('.git')
                self.backend = GitSource(self.istate, self.name, self.src, **self.keywds)
            elif self.src.startswith("file://"):
                if self.name == None:
                    self.name = 'filecache-' + self.src.split('/')[-1]
                self.backend = FileSource(self.istate, self.name, self.src, **self.keywds)
        elif type(self.src) == types.FunctionType:
            if self.name == None:
                self.name = 'funccache-' + self.src.func_name
            self.backend = FuncSource(self.istate, self.name, self.src, **self.keywds)

        if self.backend == None:
            raise InhibitorError("Unknown source type: %s" % (self.src,))

    
    def post_conf(self, inhibitor_state):
        self.istate     = inhibitor_state
        self._init_backend()

        self.cachedir   = self.istate.paths.cache.join(self.name)

        if self.dest:
            self.full_dest  = self.istate.paths.chroot.join(self.dest)
        else:
            self.full_dest = None

    def fetch(self, force = False):
        """
        Updates the cache. Does not catch and handle exceptions.

        @param force        - If true, force cleaning of the cache.
        """
        self._check()
        self.backend.fetch()

    def install(self):
        self._check()

        if self.dest == None:
            return
        
        if self.keep:
            dbg("Copying %s to %s" % (self.cachedir, self.full_dest))
            root, dirs, files = os.walk(self.cachedir.dname()).next()
            if not os.path.isdir(self.full_dest):
                os.mkdir(self.full_dest)
            for f in files:
                shutil.copyfile(self.cachedir.join(f), self.full_dest.join(f))
            for d in dirs:
                shutil.copytree(
                    self.cachedir.join(d),
                    self.full_dest.join(d),
                    symlinks=True,
                    ignore=self.backend.ignore)
        else:
            dbg("Bind mounting %s at %s" % (self.cachedir, self.full_dest))
            self.mount = Mount(self.cachedir, self.dest, self.istate.paths.chroot)
            mount(self.mount, self.istate.mount_points)

    def clean(self):
        self._check()

        if self.dest == None:
            return

        if self.keep:
            dbg("Cleaning %s from %s" % (self.cachedir, self.full_dest))
            shutil.rmtree(self.full_dest)
        else:
            dbg("Unmounting %s from %s" % (self.cachedir, self.full_dest))
            umount(self.mount, self.istate.mount_points)

        self.backend.clean()

    def pack(self):
        self._check()
        return self.backend.pack()

class _GenericSource(object):
    """
    Generic source object.

    @param inhibitor_state      - Inhibitor Configuration
    @param src                  - Source path.
    @param name                 - Unique identifier for this source object.
    """
    def __init__(self, inhibitor_state, name, src):
        self.istate     = inhibitor_state
        self.name       = name
        self.src        = src
        self.cachedir   = self.istate.paths.cache.join(self.name)
        self.ignore     = shutil.ignore_patterns('.svn', '.git', '*.swp')

    def clean_cache(self, force=False):
        if force:
            if os.path.exists(self.cachedir):
                shutil.rmtree(self.cachedir)
 
    def fetch(self):
        raise InhibitorError("fetch() is undefined for %s" % (name,))

    def clean(self):
        pass

    def tar_exclude(self, filename):
        ret = filename not in ('.svn', '.git', '*.swp')
        print filename, ret
        return ret

    def pack(self):
        fpath = self.cachedir + '.tar.bz2'
        dbg("Creating %s from %s" % (fpath, self.cachedir))
        archive = tarfile.open(fpath, 'w:bz2')
#        wd = os.getcwd()
#        os.chdir(self.cachedir+'/../')
        for root, dirs, files in os.walk(self.cachedir):
            include = dirs[:]
            include.extend(files)
            striplen = len(self.cachedir) + 1
            for f in include:
                if f in ('.svn', '.git'):
                    continue
                full_path = os.path.join(root,f)
                archive.add(full_path,
                    arcname = full_path[striplen:],
                    recursive = False )

#        try:
#            f.add(self.name, recursive=True, exclude=self.tar_exclude)
#        except:
#            os.chdir(wd)
#            raise
        archive.close()
        return fpath

class FileSource(_GenericSource):
    def __init__(self, inhibitor_state, name, src, **keywds):
        real_src = Path(src[6:])
        super(FileSource, self).__init__(inhibitor_state, name, real_src)

    def fetch(self):
        self.clean_cache(force=True)
        shutil.copytree(
            self.src,
            self.cachedir.dname(),
            symlinks=True,
            ignore=self.ignore)


class FuncSource(_GenericSource):
    def __init__(self, inhibitor_state, name, src, **keywds):
        super(FuncSource, self).__init__(inhibitor_state, name, src)
        self.keywds = keywds

    def fetch(self):
        self.clean_cache(force=True)
        os.makedirs(self.cachedir)
        ret_dict = self.src(self.keywds)
        self._write_dictionary(self.cachedir, ret_dict)

    def _write_dictionary(self, destdir, dict):
        for k,v in dict.items():
            if type(v) == types.StringType:
                # Find the indentation level of the first line so we can strip
                # that from any following lines.  Allows use of multi-line strings
                # in the return dictionary with correct python indentation.
                b = v.lstrip('\n\t ')
                strip = len(v) - len(b) - 1
                f = open(destdir.join(k), 'w')
                for line in v.splitlines():
                    f.write(line[strip:]+'\n')
                f.close()
            else:
                os.makedirs(destdir.join(k))
                self._write_dictionary(destdir.join(k), v)
            
        


class GitSource(_GenericSource):
    """
    Git source object.  Special case where we do not wipe out the
    cachedir and instead pull from the origin and checkout branches.
    """

    def __init__(self, inhibitor_state, name, src, **keywds):
        super(GitSource, self).__init__(inhibitor_state, name, src)
        if 'rev' in keywds:
            self.rev        = keywds['rev']
        else:
            self.rev        = 'HEAD'
        self.cleaned_cache  = False
        self.gitdir         = self.cachedir.join('.git')
        self.env            = {'GIT_DIR':self.gitdir}

    def _get_remote_fetch(self):
        """
        Returns a list of origins we fetch from
        """
        rc, out = cmd_out('git remote -v', env=self.env)
        remotes = []
        for line in out.splitlines():
            name, tmp = line.split('\t')
            url, type = tmp.split(' ')
            if 'fetch' in type:
                remotes.append(url)
        return remotes

    def clean_cache(self, force=False):
        self.cleaned_cache = True
       
        if force and os.path.exists(self.cachedir):
            shutil.rmtree(self.cachedir)
            return

        if os.path.isdir(self.gitdir):
            if not self.src in self._get_remote_fetch():
                warn("Deleting %s as %s is not in the remote list"
                    % (self.cachedir, self.src))
                shutil.rmtree(self.cachedir)
            else:
                return
        elif os.path.exists(self.cachedir):
            warn("Removing non - git clone %s" % (self.cachedir,))
            shutil.rmtree(self.cachedir)

    def fetch(self):
        if not self.cleaned_cache:
            self.clean_cache(force=False)

        if os.path.isdir(self.gitdir):
            cmd('git reset --hard', env=self.env, chdir=self.cachedir)
            cmd('git checkout master', env=self.env, chdir=self.cachedir)
            cmd('git pull', env=self.env)
        else:
            cmd('git clone %s %s' % (self.src, self.cachedir))

        rc, branches = cmd_out('git branch -l', env=self.env, chdir=self.cachedir)
        if 'inhibitor' in branches:
            cmd('git branch -D inhibitor', env=self.env, chdir=self.cachedir)
        
        if self.rev != 'HEAD':
            cmd('git checkout -b inhibitor %s' % self.rev, env=self.env, chdir=self.cachedir)
        else:
            rc, self.rev = cmd_out('git rev-parse HEAD', env=self.env)
            self.rev = self.rev[:7]

    def clean(self):
        rc, branches = cmd_out('git branch -l', env=self.env)
        if 'inhibitor' in branches:
            cmd('git checkout master', env=self.env, chdir=self.cachedir)
            cmd('git branch -D inhibitor', env=self.env)

    def pack(self):
        tarfile = "%s-%s.tar.bz2" % (self.name, self.rev)
        tarpath = os.path.dirname(self.cachedir) + '/' + tarfile
        cmd('git archive --format=tar %s | bzip2 --fast -f > %s'
            % (self.rev, tarpath),
            env=self.env, chdir=self.cachedir)
        return tarpath



