import shutil
import os
import tarfile
import types
import time

import util


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
        self.src        = src
        self.dest       = dest
        self.name       = name
        self.keep       = keep
        self.keywds     = keywds

        self.backend    = None
        self.cachedir   = None
        self.istate     = None
        self.fetched    = False

    def _check(self):
        if not self.istate:
            raise util.InhibitorError(
                "post_conf() not yet called for InhibitorSource %s" % self.name)
    
    def _init_backend(self):
        if type(self.src) == types.StringType:
            if self.src.startswith("git://"):
                if self.name == None:
                    self.name = self.src.split('/')[-1].rstrip('.git')
                self.backend = GitSource(self.istate, self.name, self.src, self.keep, **self.keywds)
            elif self.src.startswith("file://"):
                if self.name == None:
                    self.name = 'filecache-' + self.src.split('/')[-1]
                self.backend = FileSource(self.istate, self.name, self.src, self.keep, **self.keywds)
        elif type(self.src) == types.FunctionType:
            if self.name == None:
                self.name = 'funccache-' + self.src.func_name
            self.backend = FuncSource(self.istate, self.name, self.src, self.keep, **self.keywds)

        if self.backend == None:
            raise util.InhibitorError("Unknown source type: %s" % (self.src,))

    
    def post_conf(self, inhibitor_state):
        self.istate     = inhibitor_state
        self._init_backend()
        self.cachedir   = self.istate.paths.cache.pjoin(self.name)

    def fetch(self):
        """
        Updates the cache. Does not catch and handle exceptions.

        @param force        - If true, force cleaning of the cache.
        """
        self._check()
        self.backend.fetch()
        self.fetched = True

    def install(self):
        self._check()
        if self.dest == None:
            return
        if not self.fetched:
            self.fetch()
        self.backend.install(self.istate.paths.chroot, self.dest)
        

    def clean(self):
        self._check()
        if self.dest == None or self.keep:
            return
        self.backend.clean(self.istate.paths.chroot, self.dest)

    def pack(self):
        self._check()
        if not self.fetched:
            self.fetch()
        return self.backend.pack()

class _GenericSource(object):
    """
    Generic source object.

    @param inhibitor_state      - Inhibitor Configuration
    @param src                  - Source path.
    @param name                 - Unique identifier for this source object.
    """
    def __init__(self, inhibitor_state, name, src, keep):
        self.istate     = inhibitor_state
        self.name       = name
        self.src        = src
        self.keep       = keep
        self.cachedir   = self.istate.paths.cache.pjoin(self.name)
        self.ignore     = shutil.ignore_patterns('.svn', '.git', '*.swp')
        self.src_is_dir = False
        self.mount      = None

    def clean_cache(self, force=False):
        if self.src_is_dir and force:
            if os.path.exists(self.cachedir):
                shutil.rmtree(self.cachedir)
 
    def fetch(self):
        raise util.InhibitorError("fetch() is undefined for %s" % (self.name,))

    def clean(self, root, dest):
        if self.mount:
            util.umount(self.mount, self.istate.mount_points)
        else:
            if not self.src_is_dir:
                os.unlink(root.pjoin(dest))
            else:
                shutil.rmtree(root.pjoin(dest))

    def pack(self):
        if self.src_is_dir:
            util.warn("Refusing to pack source %s as it's a file" % (self.name))
            return

        fpath = self.cachedir + '.tar.bz2'
        util.dbg("Creating %s from %s" % (fpath, self.cachedir))
        archive = tarfile.open(fpath, 'w:bz2')
        for root, dirs, files in os.walk(self.cachedir):
            include = dirs[:]
            include.extend(files)
            striplen = len(self.cachedir) + 1
            for f in include:
                if f in ('.svn', '.git'):
                    continue
                full_path = os.path.pjoin(root, f)
                archive.add(full_path,
                    arcname = full_path[striplen:],
                    recursive = False )
        archive.close()
        return fpath

    def install(self, root, dest):
        full_dest = root.pjoin(dest)

        # It's a file, always copy from source.
        if not self.src_is_dir:
            util.dbg("Copying %s to %s" % (self.src, full_dest))
            shutil.copy(self.src, full_dest)
        else:
            # If we're keeping this, there was no reason to create a cache,
            # so we again copy directy from the source
            if self.keep:
                util.dbg("Copying %s to %s" % (self.src.dname(), full_dest.dname()))
                if not os.path.isdir(full_dest):
                    os.mkdir(full_dest)
                paths = os.listdir(self.src.dname())
                ignore = self.ignore(self.src.dname(), paths)
                for p in paths:
                    if p in ignore:
                        continue
                    if os.path.isdir(self.src.pjoin(p)):
                        shutil.copytree(
                            self.src.pjoin(p),
                            full_dest.pjoin(p),
                            symlinks=True,
                            ignore=self.ignore)
                    else:
                        shutil.copyfile(self.src.pjoin(p), full_dest.pjoin(p))
            # This is a directory that we do not plan on keeping, so we
            # bindmount from the cache.
            else:
                util.dbg("Bind mounting %s at %s" % (self.cachedir, full_dest))
                self.mount = util.Mount(self.cachedir, dest, root)
                util.mount(self.mount, self.istate.mount_points)


class FileSource(_GenericSource):
    def __init__(self, inhibitor_state, name, src, keep, **keywds):
        real_src = util.Path(src[6:])
        super(FileSource, self).__init__(inhibitor_state, name, real_src, keep)
        if os.path.isdir(self.src):
            self.src_is_dir = True

    def fetch(self):
        if not self.src_is_dir or self.keep:
            return
        else:
            self.clean_cache(force=True)
            shutil.copytree(
                self.src,
                self.cachedir.dname(),
                symlinks=True,
                ignore=self.ignore)


class FuncSource(_GenericSource):
    def __init__(self, inhibitor_state, name, src, keep, **keywds):
        super(FuncSource, self).__init__(inhibitor_state, name, src, keep)
        self.keywds = keywds
        self.output = None

    def fetch(self):
        self.output = self.src(self.keywds)
        if not type(self.output) in (types.DictType, types.StringType):
            raise util.InhibitorError("Function %s returned invalid type %s"
                % (self.name, str(type(self.output))) )

    def _write_dictionary(self, destdir, d):
        for k,v in d.items():
            if type(v) == types.StringType:
                self._write_file(destdir.join(k), v)
            else:
                os.makedirs(destdir.pjoin(k))
                self._write_dictionary(destdir.pjoin(k), v)

    @staticmethod
    def _write_file(path, value):
        # Find the indentation level of the first line so we can strip
        # that from any following lines.  Allows use of multi-line strings
        # in the return dictionary with correct python indentation.
        b = value.lstrip('\n\t ')
        strip = len(value) - len(b) - 1
        f = open(path, 'w')
        for line in value.splitlines():
            f.write(line[strip:]+'\n')
        f.close()
 
    def install(self, root, dest):
        nkeys = None
        if type(self.output) == types.DictType:
            nkeys = len(self.output.keys())

        if type(self.output) == types.StringType:
            util.dbg("Writing string output to %s" % (root.pjoin(dest)))
            self._write_file(root.pjoin(dest), self.output)
        elif nkeys == 1:
            util.dbg("Writing singleton dictionary output to %s" % (root.pjoin(dest)))
            k = self.output.keys()[0]
            self._write_file(root.pjoin(dest), self.output[k])
        else:
            util.dbg("Writing dictionary output to %s" % (root.pjoin(dest)))
            self._write_dictionary(root.join(dest), self.output)
         

class GitSource(_GenericSource):
    """
    Git source object.  Special case where we do not wipe out the
    cachedir and instead pull from the origin and checkout branches.
    """

    def __init__(self, inhibitor_state, name, src, keep, **keywds):
        super(GitSource, self).__init__(inhibitor_state, name, src, keep)
        self.src_is_dir     = True
        if 'rev' in keywds:
            self.rev        = keywds['rev']
        else:
            self.rev        = 'HEAD'
        self.cleaned_cache  = False
        self.gitdir         = self.cachedir.pjoin('.git')
        self.env            = {'GIT_DIR':self.gitdir}

    def _get_remote_fetch(self):
        """
        Returns a list of origins we fetch from
        """
        _, out = util.cmd_out('git remote -v', env=self.env)
        remotes = []
        for line in out.splitlines():
            _, tmp = line.split('\t')
            url, what = tmp.split(' ')
            if 'fetch' in what:
                remotes.append(url)
        return remotes

    def clean_cache(self, force=False):
        self.cleaned_cache = True
       
        if force and os.path.exists(self.cachedir):
            shutil.rmtree(self.cachedir)
            return

        if os.path.isdir(self.gitdir):
            if not self.src in self._get_remote_fetch():
                util.warn("Deleting %s as %s is not in the remote list"
                    % (self.cachedir, self.src))
                shutil.rmtree(self.cachedir)
            else:
                return
        elif os.path.exists(self.cachedir):
            util.warn("Removing non - git clone %s" % (self.cachedir,))
            shutil.rmtree(self.cachedir)

    def fetch(self):
        if not self.cleaned_cache:
            self.clean_cache(force=False)

        if os.path.isdir(self.gitdir):
            util.cmd('git reset --hard', env=self.env, chdir=self.cachedir)
            util.cmd('git checkout master', env=self.env, chdir=self.cachedir)
            util.cmd('git pull', env=self.env)
        else:
            util.cmd('git clone %s %s' % (self.src, self.cachedir))

        _, branches = util.cmd_out('git branch -l', env=self.env, chdir=self.cachedir)
        if 'inhibitor' in branches:
            util.cmd('git branch -D inhibitor', env=self.env, chdir=self.cachedir)
        
        if self.rev != 'HEAD':
            util.cmd('git checkout -b inhibitor %s' % self.rev, env=self.env, chdir=self.cachedir)
        else:
            _, self.rev = util.cmd_out('git rev-parse HEAD', env=self.env)
            self.rev = self.rev[:7]

    def clean(self, root, dest):
        super(GitSource, self).clean(root, dest)
        _, branches = util.cmd_out('git branch -l', env=self.env)
        if 'inhibitor' in branches:
            util.cmd('git checkout master', env=self.env, chdir=self.cachedir)
            util.cmd('git branch -D inhibitor', env=self.env)

    def pack(self):
        tarpath = "%s-%s.tar.bz2" % (self.name, self.rev)
        tarpath = os.path.dirname(self.cachedir) + '/' + tarpath
        util.cmd('git archive --format=tar %s | bzip2 --fast -f > %s'
            % (self.rev, tarpath),
            env=self.env, chdir=self.cachedir)
        return tarpath


class InhibitorScript(InhibitorSource):
    def __init__(self, name, src, args = None, needs=[]):
        super(InhibitorScript, self).__init__(
            src,
            dest = util.Path('/tmp/inhibitor/sh').pjoin(name),
            name = name,
            keep = False)
        if args != None:
            if type(args) == types.StringType:
                self.args = args.split(" ")
            elif type(args) == types.ListType:
                self.args = args
            else:
                raise util.InhibitorError("Arguments to script %s are not a string or list" % name)
        else:
            self.args = []

        self.reqs = []
        if type(needs) == InhibitorSource:
            needs = [needs]
        for need in needs:
            need.dest = util.Path('/tmp/inhibitor/sh').pjoin(os.path.basename(need.src))
            need.keep = False
            self.reqs.append(need)

    def post_conf(self, inhibitor_state):
        super(InhibitorScript, self).post_conf(inhibitor_state)
        for req in self.reqs:
            req.post_conf(inhibitor_state)
    
    def install(self):
        super(InhibitorScript, self).install()
        os.chmod(self.istate.paths.chroot.pjoin(self.dest), 0755)
        for req in self.reqs:
            req.install()


    def run(self, chroot):
        cmd = 'chroot %s /tmp/inhibitor/sh/%s' % (chroot, self.name)
        if self.args:
            for arg in self.args:
                cmd += " '%s'" % (arg,)
        env = {
            'INHIBITOR_SCRIPT_ROOT':'/tmp/inhibitor/sh'
        }
        try:
            util.cmd(cmd, env=env)
        except (KeyboardInterrupt, SystemExit):
            util.info("Caught SIGTERM or SIGINT:  Waiting for children to die")
            # XXX:  Hacky.
            time.sleep(5)
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError("Caught KeyboardInterrupt or SystemExit")
        except Exception, e:
            util.umount_all(self.istate.mount_points)
            raise util.InhibitorError(str(e))






