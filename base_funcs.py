import hashlib
import subprocess
import tempfile 
import time
import os
import signal
import sys
import types
import glob

class InhibitorError(Exception):
    def __init__(self, message):
        umount_all()
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

def umount_all(root=None):
    global mount_list

    umount_order = sorted(mount_list.keys())
    umount_order.reverse()
    
    for mp in umount_list:
        umount(mp, root=root)
   

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



