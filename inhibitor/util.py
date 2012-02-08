import sys
import types
import subprocess
import tempfile
import os.path
import shutil
import glob
import signal
import time

# This is only needed for Gentoo builds.
try:
    import portage.util
except ImportError:
    pass

INHIBITOR_DEBUG = False

class InhibitorError(Exception):
    def __init__(self, message):
        super(InhibitorError, self).__init__(message)
        print
        print
        err("Exception Raised:  Cleaning up.\n")

    def __str__(self):
        ret = '\n'
        ret += "\001\033[0;31m\002*\001\033[0m\002 %s" % "Error:  "
        for i in self.args:
            ret += '%s ' % i
        return ret

class Path(types.StringType):
    """
    Wrapper around paths to ensure we canonicalize and join them correctly
    """
    def __new__( cls, value ):
        return types.StringType.__new__(cls, os.path.normpath(value))

    def dname(self):
        """Return path as a directory, i.e. a trailing '/'"""
        return str(self) + "/"

    def pjoin(self, *paths):
        """Return a new Path by joining this one with the specified paths"""
        return Path(self.dname() + '/'.join(paths))

class Container(object):
    """
    Contains any number of named objects.  Very similar to a dictionary but
    variables are simply access by keyword.

    @param keys     - list of key value pairs.
    """
    def __init__(self, **keys):
        self.keys = []
        for k, v in keys.items():
            setattr(self, k, v)
            self.keys.append(k)

    def has(self, key):
        """Return True if this container has the specified key"""
        return hasattr(self, key)

    def update(self, key, value):
        """Update key with new value"""
        setattr(self, key, value)
        self.keys.append(key)

class Mount(object):
    """
    Contains a mount definition.

    @param src  - Path to the source of the mount path.
    @param dest - Path, inside the root, to mount src.
    @param root - Path to the root of the destination path.
    """
    def __init__(self, src, dest, root):
        self.src    = Path(src)
        self.dest   = Path(dest)
        self.root   = Path(root)
        self.rmdir  = False

    def __str__(self):
        return "src: %s -- dest: %s -- root: %s" % (
            self.src, self.dest, self.root)

class Step(Container):
    """
    Container for a function to be run, pairing it with the name of
    the action the function will be preforming.
    """
    def __init__(self, function, always=True, **keywds):
        self.function = types.FunctionType
        super(Step, self).__init__(function=function, always=always, **keywds)
        self.name = function.func_name

    def run(self):
        self.function()


def info(message):
    print "\001\033[0;32m\002*\001\033[0m\002 %s" % message

def warn(message):
    print "\001\033[1;33m\002*\001\033[0m\002 %s" % message

def err(message):
    print "\001\033[0;31m\002*\001\033[0m\002 %s" % message

def dbg(message):
    if INHIBITOR_DEBUG:
        print "\001\033[1;36m\002*\001\033[0m\002 %s" % message
        sys.stdout.flush()


# Mounting utilities
def mount(mp, mounts, options='-o bind'):
    """
    Activate (mount) a Mount.

    @param mp       - Mount to activate.
    @param mounts   - List of Mounts currently active.
    @param options  - String of extra options to pass to the mount command
    """
    if mp in mounts:
        dbg("Mount(%s) is already mounted" % (mp,))
        return

    full_dest = mp.root.pjoin(mp.dest)
    if not os.path.isdir(full_dest):
        os.makedirs(full_dest)
        mp.rmdir = True
    cmd('mount ' + options + ' %s %s' % (mp.src, mp.root.pjoin(mp.dest)) )
    mounts.append(mp)

def umount(mp, mounts):
    """
    Deactivate (unmount) a Mount.

    @param mp       - Mount to deactivate.
    @param mounts   - List of mounts currently active.
    """
    if not mp in mounts:
        dbg("Mount(%s) is already unmounted" % (mp,))
        return

    while mp in mounts:
        mounts.remove( mp )

    fp = mp.root.pjoin(mp.dest)
    if cmd('umount %s' % fp, raise_exception=False) != 0:
        warn('Unmount of %s failed.' % fp)
        warn('Killing any processes still running in %s' % mp.root)
        pl = []
        for root in glob.glob('/proc/[0-9][0-9]*/root'):
            try:
                if os.readlink(root).startswith(mp.root):
                    pl.append( root[len('/proc/'):-len('/root')] )
            except OSError, e:
                # Catch the process having already exited.
                if e.errno == 2:
                    continue
        _kill_pids(pl)

        if cmd('umount -f %s' % fp, raise_exception=False) != 0:
            err('Cound not unmount %s' % fp)
            return False
    if mp.rmdir:
        shutil.rmtree(fp)
    return True


def umount_all(mounts):
    """
    Deactivate (unmount) all Mounts.

    @param mounts   - List of mounts currently active.
    """
    mounts.reverse()
    while len(mounts) > 0:
        umount(mounts[0], mounts)

def _kill_pids(pids, ignore_exceptions=True):
    if type(pids) == int:
        pids = [pids]

    for p in pids:
        p = int(p)
        if p == -1 or not os.path.isdir('/proc/%d' %p):
            continue
        try:
            os.kill(p, signal.SIGTERM)
            time.sleep(0.1)
            if os.waitpid(p, os.WNOHANG)[1] == 0:
                os.kill(p, signal.SIGKILL)
                os.waitpid(p, 0)
        except OSError, e:
            if os.path.isdir('/proc/%d') and ignore_exceptions:
                warn('Failed to kill %d' % (p,))
                pass
            if not e.errno in (10, 3):
                raise e

def _spawn(cmdline, env={}, return_output=False, timeout=0, exe=None, chdir=None):
    if type(cmdline) == types.StringType:
        cmdline = cmdline.split()

    if exe == None:
        exe = cmdline[0]

    if return_output:
        dbg("Getting output from '%s'" % ' '.join(cmdline))
        fout = tempfile.NamedTemporaryFile()
    else:
        dbg("Calling '%s'" % ' '.join(cmdline))
        fout = sys.stdout

    try:
        child = subprocess.Popen(cmdline, shell=False, executable=exe,
            env=env, stdout=fout, stderr=subprocess.STDOUT, close_fds=True,
            cwd=chdir)
    except (SystemExit, KeyboardInterrupt):
        _kill_pids(child.pid)
        raise
    except OSError, e:
        raise InhibitorError("Failed to spawn '%s': %s" % (cmdline, e))

    if timeout == 0:
        try:
            ret = child.wait()
        except (SystemExit, KeyboardInterrupt):
            raise InhibitorError(
                "Caught SystemExit or KeyboardInterrupt while running %s"
                % (cmdline))
    else:
        start_time = time.time()
        ctime = start_time
        while True:
            time.sleep(1)
            ret = child.poll()
            if ret != None:
                break

            ctime = time.time()
            if (start_time + timeout) >= ctime:
                _kill_pids(child.pid)
                raise InhibitorError("Timeout (%d seconds) waiting for '%s'"
                    % (int(timeout), cmdline))

    if return_output:
        fout.flush()
        fout.seek(0)
        output = fout.read()
        ret = (ret, output)
        fout.close()
    return ret

def _spawn_sh(cmdline, env, chdir=None, return_output=False, shell='/bin/bash'):
    args = [shell, '-c']
    if '|' in cmdline:
        # Make sure we get a real return value.
        cmdline = "set -o pipefail;" + cmdline

    args.append(cmdline)

    return _spawn(args, env, exe=shell, chdir=chdir, return_output=return_output)

def cmd(cmdline, env={}, raise_exception=True, chdir=None, shell='/bin/bash'):
    """
    Call a command using bash.  If piping is detected, pipefail will be set.

    @param cmdline          - Command to call, a string
    @param env              - Environment dictionary.  ({})
    @param raise_exception  - Raise exception on non-zero return. (True)
    @param chdir            - Change to given directory before executing (None).
    @param shell            - Shell to run the command in (/bin/bash).

    Return is the return code from the command.
    """

    if type(cmdline) != types.StringType:
        raise InhibitorError("Invalid command line, not a string:  %s", (str(cmdline),))

    try:
        sys.stdout.flush()
        ret = _spawn_sh(cmdline, env, chdir=chdir, shell=shell)
        if ret != 0:
            if raise_exception:
                raise InhibitorError("'%s' returned %d" % (cmdline, ret))
    except:
        raise
    return ret

def cmd_out(cmdline, env={}, raise_exception=True, chdir=None, shell='/bin/bash'):
    """
    Call a command using bash.  If piping is detected, pipefail will be set.

    @param cmdline          - Command to call, a string
    @param env              - Environment dictionary.  ({})
    @param raise_exception  - Raise exception on non-zero return. (True)
    @param chdir            - Change to given directory before executing (None).
    @param shell            - Shell to run the command in (/bin/bash).

    Return is a pair:  (return code, output)
    """

    try:
        sys.stdout.flush()
        ret, out = _spawn_sh(cmdline, env, return_output=True, chdir=chdir, shell=shell)
        if ret != 0 and raise_exception:
            raise InhibitorError("'%s' returned %d, %s" % (cmdline, ret, out))
        if out.count('\n') <= 1:
            out = out.strip()
        return (ret, out)
    except:
        raise

def chroot(path, function, failuref=None, fargs={}, failure_args={}):
    """
    Run a function inside of a chroot.

    @param path             - Root of the chroot.
    @param function         - Function to run.
    @param failuref         - Function to run on failure (None).
    @param fargs            - Arguments to pass to function ({}).
    @param failulre_args    - Arguments to pass to failure function ({})
    """
    orig_root = os.open('/', os.O_RDONLY)
    orig_dir = os.path.realpath(os.curdir)
    old_env = {}
    old_env.update(os.environ)
    try:
        os.chroot(path)
    except (IOError, OSError):
        os.close(orig_root)
        raise

    try:
        os.chdir('/')
    except (IOError, OSError):
        os.close(orig_root)
        os.chroot('/')
        os.chdir(orig_dir)

    try:
        ret = function(**fargs)
    except (KeyboardInterrupt, SystemExit, Exception), e:
        os.fchdir(orig_root)
        os.chroot('./')
        os.close(orig_root)
        os.chdir(orig_dir)
        if failuref != None:
            failuref(**failure_args)
        err(str(e))
        raise

    os.fchdir(orig_root)
    os.chroot('./')
    os.close(orig_root)
    os.chdir(orig_dir)
    return ret

def make_conf_dict(path):
    """
    Read a make.conf file and return it as a dictionary.

    @param path - Path to make.conf file.
    """
    if os.path.exists(path):
        return portage.util.getconfig(path, allow_sourcing=True)
    else:
        return {}

def write_dict_bash(bd, path):
    """
    Write a dictionary in a bash sourceable format.

    @param bd   - Dictionary of key/value strings to write.
    @param path - Path to write to.
    """
    if type(path) == types.StringType:
        path = Path(path)

    if not os.path.isdir( os.path.dirname(path) ):
        os.makedirs(os.path.dirname(path))

    f = open(path, 'w')
    keys = bd.keys()
    keys.sort()
    for k in keys:
        f.write('%s="%s"\n' % (k, bd[k]))
    f.close()

def path_sync(src, targ, root='/', ignore=lambda x, y: [], file_copy_callback=None):
    """
    Sync one path to another precisely preserving the the layout of the source.  In
    particular if chroot works in the source, it will work identically in the target.

    @param src                  - Source path.
    @param targ                 - Destination path.
    @param root                 - Root of the target path, used to preserve non-relative
                                  symlinks.  Defaults to /.
    @param ignore               - If a function,  given a list of files returns a list
                                  to be ignored.  If a string, converted to a function
                                  using shutil.ignore_patterns.
    @param file_copy_callback   - After copying a file, this function will be called
                                  with the arguments source path, destination path.
    """
    if type(ignore) == types.FunctionType:
        ignore_func = ignore
    elif type(ignore) == types.StringType:
        ignore_func = shutil.ignore_patterns(ignore.split(' '))
    else:
        ignore_func = shutil.ignore_patterns(ignore)

    if os.path.isdir(src):
        if not os.path.isdir(targ):
            os.makedirs(targ)
        contents = os.listdir(src)
        ignore_list = ignore_func(src, contents)
        for f in contents:
            if f in ignore_list:
                continue
            path_sync(
                os.path.join(src, f),
                os.path.join(targ, f),
                ignore=ignore_func,
                root=root,
                file_copy_callback=file_copy_callback
            )
    elif os.path.islink(src):
        link = os.readlink(src)
        if not os.path.lexists( os.path.dirname(os.path.realpath(targ)) ):
            os.makedirs( os.path.dirname(os.path.realpath(targ)) )

        if os.path.lexists(targ):
            os.unlink(targ)
        os.symlink(link, targ)

        if link.startswith('/'):
            # This is tricky.  We want to follow the link and copy the contents
            # of whatever it points to.  However, as we may be building up a new
            # root filesystem, links that start with / cannot be trusted, so we
            # have to backtrack from the src path to what / actually is.
            append = ''
            for _ in range(0, src.count('/')-root.count('/')):
                append = os.path.join(append, '..')

            link = link.lstrip('/')
            src = os.path.normpath( os.path.join( os.path.dirname(src), append, link) )
            targ = os.path.normpath( os.path.join( os.path.dirname(targ), append, link) )

            if os.path.exists(src):
                path_sync( src, targ,
                    ignore=ignore_func,
                    root=root,
                    file_copy_callback=file_copy_callback
                )
        else:
            if os.path.exists(src):
                path_sync(
                    os.path.join(os.path.dirname(src), link),
                    os.path.join(os.path.dirname(targ), link),
                    ignore = ignore_func,
                    root=root,
                    file_copy_callback=file_copy_callback
                 )
    else:
        if not os.path.lexists( os.path.dirname(os.path.realpath(targ)) ):
            os.makedirs( os.path.dirname(os.path.realpath(targ)) )
        if os.path.islink(targ):
            # shutil.copy2 follows links for the dest path.
            os.unlink(targ)
        shutil.copy2(src, targ)
        if file_copy_callback != None:
            file_copy_callback(src, targ)

def strlist_to_list( strlist ):
    """
    Wrap testing if an object is a list or a string, return it
    as a list of strings.
    """
    if type(strlist) == types.StringType:
        ret = strlist.split()
    elif type(strlist) == types.ListType:
        ret = strlist
    else:
        raise InhibitorError("Cannot convert object to list.  %s" % (strlist,))
    return ret

def mkdir( path ):
    """
    Create a directory if it does not already exist.
    """
    if not os.path.lexists(path):
        os.makedirs(path)
    return path

