import sys
import types
import subprocess
import tempfile
import os.path
import shutil
import glob
import traceback

# XXX:  To remove
try:
    import portage.util as portage_util
except ImportError:
    import portage_util

INHIBITOR_DEBUG = False

class InhibitorError(Exception):
    def __init__(self, message, **keywds):
        super(InhibitorError, self).__init__(message)
        print;print
        err("Exception Raised:  Cleaning up.\n")

    def __str__(self):
        ret = '\n'
        ret += "\001\033[0;31m\002*\001\033[0m\002 %s" % "Error:  "
        for i in self.args:
            ret += '%s ' % i
        return ret

class Path(types.StringType):
    def __new__( cls, value ):
        return types.StringType.__new__(cls, os.path.normpath(value))

    def dname(self):
        return str(self) + "/" 

    def pjoin(self, *paths):
        return Path(self.dname() + '/'.join(paths))

class Container(object):
    def __init__(self, **keys):
        self.keys = []
        for k,v in keys.items():
            setattr(self, k, v)
            self.keys.append(k)

    def has(self, key):
        return hasattr(self, key)

    def update(self, key, value):
        setattr(self, key, value)
        self.keys.append(key)

class Mount(object):
    def __init__(self, src, dest, root):
        self.src    = Path(src)
        self.dest   = Path(dest)
        self.root   = Path(root)
        self.rmdir  = False

    def __str__(self):
        return "src: %s -- dest: %s -- root: %s" % (
            self.src, self.dest, self.root)

class Step(Container):
    def __init__(self, function, always=True, **keywds):
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
    global INHIBITOR_DEBUG
    if INHIBITOR_DEBUG:
        print "\001\033[1;36m\002*\001\033[0m\002 %s" % message
        sys.stdout.flush()


# Mounting utilities
def mount(mount, mounts, options='-o bind'):
    if mount in mounts:
        dbg("src=%s dest=%s root=%s already mounted" 
            % (mount.src, mount.dest, mount.root))
        return

    full_dest = mount.root.pjoin(mount.dest)
    if not os.path.isdir(full_dest):
        os.makedirs(full_dest)
        mount.rmdir = True
    cmd('mount ' + options + ' %s %s' % (mount.src, mount.root.pjoin(mount.dest)) )
    mounts.append(mount)

def umount(mount, mounts):
    if not mount in mounts:
        dbg("src=%s dest=%s root=%s not mounted" 
            % (mount.src, mount.dest, mount.root))
        return

    while mount in mounts:
        mounts.remove( mount )

    fp = mount.root.pjoin(mount.dest)
    if cmd('umount %s' % fp, raise_exception=False) != 0:
        warn('Unmount of %s failed.' % fp)
        warn('Killing any processes still running in %s' % mount.root)
        pl = []
        for root in glob.glob('/proc/[0-9][0-9]*/root'):
            if os.readlink(root).startswith(mount.root):
                pl.append( root[len('/proc/'):-len('/root')] )
        _kill_pids(pl)

        if cmd('umount %s' % fp, raise_exception=False) != 0:
            err('Cound not unmount %s' % fp)
            return False
    if mount.rmdir:
        shutil.rmtree(fp)
    return True


def umount_all(mounts):
    mounts.reverse()
    while len(mounts) > 0:
        umount(mounts[0], mounts)

def _kill_pids(pids, ignore_exceptions=True):
    if type(pids) == int:
        pids = [pids]

    for p in pids:
        if p == -1:
            continue
        try:
            os.kill(p, signal.SIGTERM)
            if os.waitpid(p, os.WNOHANG)[1] == 0:
                os.kill(p, signal.SIGKILL)
                os.waitpid(p, 0)
        except OSError, e:
            if ignore_exceptions:
                warn('Child process %d failed to die' % (p,))
                pass
            if not e.errno in [10,3]:
                raise e
    
def _spawn(cmdline, env={}, return_output=False, show_output=True, timeout=0, exe=None, chdir=None):
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
        raise InhibitorException("Failed to spawn '%s': %s" % (cmdline, e))
        
    if timeout == 0:
        ret = child.wait()
    else:
        start_time = time.time()
        ctime = start_time
        while True:
            time.sleep(1)
            ret = subprocess.poll()
            if ret != None:
                break
            
            ctime = time.time()
            if (start_time + timeout) >= ctime:
                _kill_pids(subprocess.pid)
                raise InhibitorException("Timeout (%d seconds) waiting for '%s'"
                    % (int(timeout), cmdline))

    if return_output:
        fout.flush()
        fout.seek(0)
        output = fout.read()
        ret = (ret, output) 
        fout.close()
    return ret

def _spawn_sh(cmdline, env, chdir=None, return_output=False, shell='/bin/bash'):
    args=[shell, '-c']
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
    orig_root = os.open('/', os.O_RDONLY)
    orig_dir = os.path.realpath(os.curdir)
    old_env ={}
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
    if os.path.exists(path):
        return portage_util.getconfig(path, allow_sourcing=True)
    else:
        return {}

def write_dict_bash(dict, path):
    if type(path) == types.StringType:
        path = Path(path)

    if not os.path.isdir( os.path.dirname(path) ):
        os.makedirs(os.path.dirname(path))

    f = open(path, 'w')
    keys = dict.keys()
    keys.sort()
    for k in keys:
        f.write('%s="%s"\n' % (k,dict[k]))
    f.close()

def path_sync(src, targ, root='/', ignore=lambda x,y: [], file_copy_callback=None):
    """
    TODO:  This is confusing enough it should probably be documented.
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
            for i in range(0, src.count('/')-root.count('/')):
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
