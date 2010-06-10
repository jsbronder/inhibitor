import shutil
import os
import types

import util

def create_source(src, **keywds):
    ret = None
    if type(src) == types.StringType:
        if src.startswith("git://"):
            ret = GitSource(src, **keywds)
        elif src.startswith("file://"):
            ret = FileSource(src, **keywds)
    elif type(src) == types.FunctionType:
        ret  = FuncSource(src, **keywds)

    if not ret:
        raise util.InhibitorError("Unknown source type: %s" % (src,))
    return ret

class _GenericSource(object):
    """
    Generic source object.

    @param src                  - Source path.
    @param dest                 - Destination within the stage4 chroot.
    @param name                 - Unique identifier for this source object.  If
                                  set to none, this is parsed out of the src dependent
                                  upon type.
    @param keep                 - Leave output in the stage4 build.
    @param rev                  - Revision of the source to use.  See
 
    @param inhibitor_state      - Inhibitor Configuration
    @param src                  - Source path.
    @param name                 - Identifier for this source object.
    """
    def __init__(self, src, 
            inhibitor_state = None,
            dest            = None,
            keep            = False,
            mountable       = False,
            cachedir        = None,
            ignore          = None,
            **keywds                ):
        self.src        = src
        self.istate     = inhibitor_state
        self.dest       = dest
        self.keep       = keep
        self.mountable  = mountable
        self.cachedir   = cachedir
        self.mount      = None
        self.installed  = []

        if ignore:
            self.ignore = ignore
        else:
            self.ignore = shutil.ignore_patterns('.svn', '.git', '*.swp')

    def post_conf(self, inhibitor_state):
        self.istate = inhibitor_state
        if self.cachedir and not self.cachedir.startswith(self.istate.paths.cache):
            self.cachedir = self.istate.paths.cache.pjoin(self.cachedir)
 
    def init(self):
        raise util.InhibitorError("init() is undefined for %s" % (self.src,))

    def file_copy_callback(self, _, targ):
        self.installed.append(targ)

    def remove(self):
        if self.mount:
            util.umount(self.mount, self.istate.mount_points)
        elif not self.keep:
            for f in self.installed:
                d = os.path.dirname(f)
                os.unlink(f)
                if len( os.listdir(d) ) == 0:
                    os.rmdir(d)

    def finish(self):
        if not self.cachedir:
            return
        shutil.rmtree(self.cachedir)

    def install(self, root):
        src = self.src
        if self.cachedir:
            src = self.cachedir
        full_dest = root.pjoin(self.dest)

        if not self.keep and self.mountable:
            util.dbg("Bind mounting %s at %s" % (src, full_dest))
            self.mount = util.Mount(src, self.dest, root)
            util.mount(self.mount, self.istate.mount_points)
        else:
            util.path_sync(
                src, 
                full_dest,
                root = root,
                ignore = self.ignore,
                file_copy_callback = self.file_copy_callback
            )
        return

class FileSource(_GenericSource):
    def __init__(self, src, inhibitor_state = None, dest = None, keep = False, **keywds):
        real_src    = util.Path(src[6:])
        mountable   = False

        if not os.path.lexists(real_src):
            raise util.InhibitorError("Path %s does not exist" % real_src)
        elif os.path.isdir(real_src):
            mountable = True

        super(FileSource, self).__init__(
            src             = real_src,
            inhibitor_state = inhibitor_state,
            dest            = dest,
            keep            = keep,
            mountable       = mountable,
            **keywds
        )

    def init(self):
        # No need to fetch, we either bind mount or copy depending on if this
        # will be left in the chroot and is a directory or not.
        return


class FuncSource(_GenericSource):
    def __init__(self, src, inhibitor_state = None, dest = None, keep = False, **keywds):
        self.output = src(**keywds)
        if not type(self.output) in (types.DictType, types.StringType):
            raise util.InhibitorError("Function %s returned invalid type %s"
                % (src.func_name, str(type(self.output))) )
        super(FuncSource, self).__init__(
            src             = src,
            inhibitor_state = inhibitor_state,
            dest            = dest,
            keep            = keep,
            **keywds
        )

    def init(self):
        # Fetching of the output is done during init as it has to happen every
        # time anyways.
        return

    def _write_dictionary(self, destdir, d):
        for k, v in d.items():
            if type(v) == types.StringType:
                self._write_file(destdir.pjoin(k), v)
            else:
                destpath = destdir.pjoin(k)
                if not os.path.lexists( destpath ):
                    os.makedirs(destdir.pjoin(k))
                self._write_dictionary(destdir.pjoin(k), v)

    def _write_file(self, path, value):
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        # Find the indentation level of the first line so we can strip
        # that from any following lines.  Allows use of multi-line strings
        # in the return dictionary with correct python indentation.
        b = value.lstrip('\n\t ')
        strip = len(value) - len(b) - 1
        if strip < 0:
            strip = 0
        f = open(path, 'w')
        for line in value.splitlines():
            f.write(line[strip:]+'\n')
        f.close()
        self.file_copy_callback(None, path)
 
    def install(self, root):
        realdest = root.pjoin(self.dest)
        if not os.path.exists( os.path.dirname(realdest) ):
            os.makedirs( os.path.dirname(realdest) )

        if type(self.output) == types.StringType:
            util.dbg("Writing string output to %s" % (realdest,))
            self._write_file(realdest, self.output)
        else:
            util.dbg("Writing dictionary output to %s" % (realdest,))
            self._write_dictionary(realdest, self.output)
         

class GitSource(_GenericSource):
    """
    Git source object.  Special case where we do not wipe out the
    cachedir and instead pull from the origin and checkout branches.
    """

    def __init__(self, src, inhibitor_state = None, dest = None, keep = False, rev = None, **keywds):
        self.env        = {}
        self.gitdir     = None
        self.rev        = rev or 'HEAD'
        cachedirname    = src.split('/')[-1].rstrip('.git')

        super(GitSource, self).__init__(
            src             = src,
            inhibitor_state = inhibitor_state,
            dest            = dest,
            keep            = keep,
            mountable       = True,
            cachedir        = cachedirname,
            **keywds
        )
        
    def post_conf(self, inhibitor_status):
        super(GitSource, self).post_conf(inhibitor_status)
        self.gitdir = self.cachedir.pjoin('.git')
        self.env    = {'GIT_DIR':self.gitdir}

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

    def clean_cache(self):
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

    def init(self):
        self.clean_cache()

        if os.path.isdir(self.gitdir):
            util.cmd('git reset --hard HEAD', env=self.env, chdir=self.cachedir)
            util.cmd('git clean -f', env=self.env, chdir=self.cachedir)
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

    def finish(self):
        self.clean_cache()


class InhibitorScript(object):
    def __init__(self, name, src, args = [], needs=[], **keywds):
        self.local_src = util.Path('/tmp/inhibitor/sh/').pjoin(name)
        self.script = create_source( 
            src,
            keep = False,
            dest = self.local_src )

        self.args = util.strlist_to_list(args)
        self.reqs = []

        if type(needs) != types.ListType:
            needs = [needs]

        for need in needs:
            need.dest = util.Path('/tmp/inhibitor/sh') #.pjoin(os.path.basename(need.src))
            need.keep = False
            self.reqs.append(need)

    def post_conf(self, inhibitor_state):
        self.script.post_conf(inhibitor_state)
        self.script.init()
        for req in self.reqs:
            req.post_conf(inhibitor_state)
            req.init()
    
    def install(self, root):
        self.script.install(root)
        os.chmod(root.pjoin(self.local_src), 0755)
        for req in self.reqs:
            req.install(root)

    def remove(self):
        self.script.remove()
        for req in self.reqs:
            req.remove()

    def finish(self):
        self.script.finish()
        for req in self.reqs:
            req.finish()

    def cmdline(self):
        cmd = str(self.local_src)
        if self.args:
            for arg in self.args:
                cmd += " '%s'" % (arg,)
        return cmd






