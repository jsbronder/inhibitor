import os
import shutil
import util
import glob
import tarfile
import types

class InhibitorAction(object):
    """
    Basic action.  Handles running through the action_sequence and catching
    errors that can be passed back up in order to do cleaning first.

    @param name     - String representing this action
    @param resume   - Allow the action sequence to resume where it left off it
                      it was previously interrupted.
    """
    def __init__(self, name='BlankAction', resume=False):
        self.name               = name
        self.action_sequence    = []
        self.resume             = resume
        self.statedir           = None
        self.istate             = None

    def get_action_sequence(self):
        return []

    def post_conf(self, inhibitor_state):
        self.istate     = inhibitor_state
        self.statedir   = inhibitor_state.paths.state.pjoin(self.name)
        if os.path.isdir(self.statedir) and not self.resume:
            self.clear_resume()
            os.makedirs(self.statedir)
        elif not os.path.exists(self.statedir):
            os.makedirs(self.statedir)
            self.resume = False
        elif len(os.listdir(self.statedir)) == 0:
            self.resume = False

    def run(self):
        for action in self.get_action_sequence():
            resume_path = self.statedir.pjoin('resume-%s-%s' % (self.name, action.name))
            if ( self.resume 
                    and action.always == False 
                    and os.path.exists(resume_path) ):
                continue
            # Errors are caught by Inhibitor()
            util.info("Running %s" % action.name)
            action.run()
            open(resume_path, 'w').close()
        self.clear_resume()

    def clear_resume(self):
        for f in glob.iglob(self.statedir.pjoin('resume-%s-*' % self.name)):
            os.unlink(f)
        os.rmdir(self.statedir)


class InhibitorSnapshot(InhibitorAction):
    """
    Create a snapshot of an InhibitorSource

    @param snapshot_source  - Source that we will generate a snapshot from.
    @param name             - Unique string to identify the source.
    @param exclude          - A string, list or tuple of patterns to not include in
                              the snapshot.  Passed to rsync --exclude.
    @param include          - String, passed to glob, of toplevel paths to include
                              in the snapshot.
    """
    def __init__(self, snapshot_source, name, exclude=None, include=None):
        super(InhibitorSnapshot, self).__init__(name='snapshot')
        self.dest       = None
        self.builddir   = None
        self.tarname    = None
        self.dest       = None

        self.name       = name
        self.src        = snapshot_source
        self.src.keep   = True
        self.src.dest   = util.Path('/')

        if exclude:
            if type(exclude) == types.StringType:
                self.exclude = exclude.split(' ')
            elif type(exclude) in (types.ListType, types.TupleType):
                self.exclude = exclude
            else:
                raise util.InhibitorError("Unrecognized exclude pattern.")
        else:
            self.exclude = False

        if include:
            if type(include) == types.StringType:
                self.include = include.split(' ')
            elif type(include) in (types.ListType, types.TupleType):
                self.include = include
            else:
                raise util.InhibitorError("Unrecognized include pattern.")
        else:
            self.include = False

    def get_action_sequence(self):
        return [
            util.Step(self.sync,     always=False),
            util.Step(self.pack,     always=False),
        ]

    def post_conf(self, inhibitor_state):
        super(InhibitorSnapshot, self).post_conf(inhibitor_state)
        self.src.post_conf(inhibitor_state)
        self.src.init()

        self.tarname    = 'snapshot-' + self.name
        self.dest       = inhibitor_state.paths.stages.pjoin(self.tarname+'.tar.bz2')
        self.builddir   = inhibitor_state.paths.build.pjoin(self.tarname)

    def sync(self):
        if os.path.exists(self.builddir):
            shutil.rmtree(self.builddir)
        elif os.path.islink(self.builddir):
            os.unlink(self.builddir)
        os.makedirs(self.builddir)

        exclude_cmd = ''
        if self.exclude:
            for i in self.exclude:
                exclude_cmd += " --exclude='%s'" % i

        if self.include:
            for pattern in self.include:
                paths = [self.src.cachedir.pjoin(pattern)]
                if '*' in pattern:
                    paths = glob.glob(self.src.cachedir.pjoin(pattern))

                for path in paths:
                    dest = path.replace(self.src.cachedir, self.builddir)
                    if not os.path.lexists( os.path.dirname(dest) ):
                        os.makedirs( os.path.dirname(dest) )
                    util.cmd('rsync -a %s %s/ %s/' % (
                        exclude_cmd,
                        path,
                        dest
                    ))
        else:
            util.cmd('rsync -a %s %s/ %s/' % (exclude_cmd, self.src.cachedir, self.builddir))

    def pack(self):
        archive = tarfile.open(self.dest, 'w:bz2')
        archive.add(self.builddir,
            arcname = '/',
            recursive = True
        )
        archive.close()
        util.info('%s is ready.' % self.dest)

