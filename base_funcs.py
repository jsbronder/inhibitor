import hashlib
import subprocess
import tempfile 
import time
import os
import signal
import sys
import types

catalyst_support = True
inhibitor_debug = False

mount_list = {}

def info(message):
    print "\001\033[0;32m\002*\001\033[0m\002 %s" % message

def warn(message):
    print "\001\033[1;33m\002*\001\033[0m\002 %s" % message

def err(message):
    print "\001\033[0;31m\002*\001\033[0m\002 %s" % message

def dbg(message):
    if inhibitor_debug:
        print "\001\033[1;36m\002*\001\033[0m\002 %s" % message

class InhibitorError(Exception):
    def __init__(self, message):
        sys.stdout.flush()
        sys.stderr.flush()
        if message:
            try:
                (type, value) = sys.exec_info()[:2]
            except AttributeError:
                value = None

            if value != None:
                print
                print traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            print
            err("Inhibitor Error:  %s" % message)
            print
            sys.exit(1)


def umount(key, root=None):
    global mount_list
    if not key or not key in mount_list:
        err('base_funcs.umount called with invalid key \'%s\'' % key)
        return False

    md = mount_list[key]
    if root and not md['root'].startswith(root):
        # This mount is not inside of the root we wish to remove everything from
        return True

    if cmd('umount %s' % key, raise_exception=False) != 0:
        warn('Unmount of %s failed.' % key)
        warn('Killing any processes still running in %s' % md['root']
        pl = []
        for root in glob.glob('/proc/[0-9][0-9]*/root'):
            if os.readlink(root).startswith(dir):
                pl.append( root[len('/proc/'):-len('/root')] )
        _kill_pids(pl)

        if cmd('umount %s' % key, raise_exception=False) != 0:
            err('Cound not unmount %s' % key)
            return False

    return True


def umount_all(root=None)
    global mount_list

    umount_order = sorted(mount_list.keys())
    umount_order.reverse()
    
    for mp in umount_list:
        umount(mp, root=root)
   
def mount(src, dest, root, type='bind'):
    global mount_list

    src = os.path.normpath(src)
    dest = os.path.normpath(dest)
    root = os.path.normpath(root)
    if dest in mount_list:
        raise CatalystError('%s is already in the mount list' % dest)

    cmd = 'mount '
    if type == 'bind':
        cmd += '-o bind '
    else:
        raise InhibitorError('Unknown mount type \'%s\'' %type)

    cmd += '%s %s' % (src, dest)
    cmd(cmd)

    mount_list[dest] = {
        'src':  src,
        'type': type,
        'root': root
    }

def file_getline(path, err_msg=""):
    if os.path.exists(path):
        if not os.access(path, os.R_OK):
            raise InhibitorError("%s: Read access to '%s' denied." % (err_msg, path))
    else:
        return None

    try:
        fd = open(path, 'r')
        l = fd.readline()
        fd.close()
    except IOError, e:
        raise InhibitorError("%s: Failed to read '%s'.  %s"
            % (err_msg, path, e.message))
    return l

def get_checksum(path, hash_type='md5'): 
    if not os.path.exists(path) or not os.access(path, os.R_OK):
        return None

    hash = hashlib.new(hash_type)
    try:
        f = open( path, 'r' )
        hash.update(f.read())
        f.close()
    except IOError, e:
        raise InhibitorError("Unable to calculate %s hash on %s: %s"
            % (hash_type, path, e.message))

    return hash.hexdigest()

def write_hashfile(dest_dir, hashed_file, hash_dict, dest_filename=None):
    if dest_filename == None:
        dest = path_join(dest_dir, os.path.basename(hashed_file+'.DIGESTS'))
    else:
        dest = path_join(dest_dir, os.path.basename(dest_filename))

    try:
        f = open(dest, 'w')
        for hash_type, hash in hash_dict.items():
            if hash == None:
                hash = get_checksum(hashed_file, hash_type)
            f.write('# %s HASH\n' % hash_type.upper())
            f.write('%s %s\n' % (hash, os.path.basename(hashed_file)))
        f.close()
    except IOError, e:
        if os.path.exists(dest):
            os.unlink(dest)
        raise InhibitorError("Unable to write hashfile to %s: %s"
            % (dest, e.message))

def path_join(*paths):
    path_list = [paths[0]]
    for p in paths[1:]:
        path_list.append(p.strip('/'))

    return os.path.normpath(os.path.join(*path_list))


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
                pass
            if not e.errno in [10,3]:
                raise e
    
def _spawn(cmdline, env={}, return_output=False, show_output=True, timeout=0, exe=None):
    if type(cmdline) == types.StringType:
        cmdline = cmdline.split()

    if exe == None:
        exe = cmdline[0]

    if return_output: 
        fout = tempfile.NamedTemporaryFile()
    else:
        info("Calling '%s'" % ' '.join(cmdline))
        fout = sys.stdout
   
    try:
        child = subprocess.Popen(cmdline, shell=False, executable=exe,
            env=env, stdout=fout, stderr=subprocess.STDOUT, close_fds=True)
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

def _spawn_bash(cmdline, env, return_output=False):
    """
    Call a command line in bash.

    WARNING:  The standard faults with bash all apply.  For instance,
    if you're depending on a return code from a|b, you will not be able
    to catch any error occuring in a.
    """
    
    args=['/bin/bash', '-c']
    if '|' in cmdline:
        # Make sure we get a real return value.
        cmdline = "set -o pipefail;" + cmdline 

    args.append(cmdline)
    if 'BASH_ENV' in env:
        env['BASH_ENV'] = '/i/learned/this/trick/from/catalyst.env'

    return _spawn(args, env, exe='/bin/bash', return_output=return_output)

def cmd(cmdline, env={}, raise_exception=True):
    try:
        sys.stdout.flush()
        ret = _spawn_bash(cmdline, env)
        if ret != 0:
            if raise_exception:
                raise InhibitorError("'%s' returned %d" % (cmdline, ret))
    except:
        raise
    return ret

def cmd_out(cmdline, env={}):
    try:
        sys.stdout.flush()
        ret, out = _spawn_bash(cmdline, env, return_output=True)
        if ret != 0:
            raise InhibitorError("'%s' returned %d, %s" % (cmdline, ret, out))
        if out.count('\n') <= 1:
            out = out.strip()
        return out
    except:
        raise

