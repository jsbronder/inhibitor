import os

import util

__version__ = '0.1'

class InhibitorState(object):
    """
    Track the state of the current inhibitor build as well as holding
    the base configuration values.

    @param paths    - Container holding default paths.
        cache       - Cache for Sources.
        stages      - Storage for completed builds.
        build       - Temporary staging directory for builds.
        pkgs        - Storage for packages.
        dist        - Storage for distfiles, shared across all builds.
        kernel      - Temporary staging directory for building kernels.
        state       - Tracks the state of each build in order to support resuming.
        share       - Path to shared support files.
    """
    def __init__(self, paths={}):

        self.paths = util.Container(
            cache       = util.Path('/var/tmp/inhibitor/%s/cache'  % __version__),
            stages      = util.Path('/var/tmp/inhibitor/%s/stages' % __version__),
            build       = util.Path('/var/tmp/inhibitor/%s/build'  % __version__),
            pkgs        = util.Path('/var/tmp/inhibitor/%s/pkgs'   % __version__),
            dist        = util.Path('/var/tmp/inhibitor/%s/dist'   % __version__),
            kernel      = util.Path('/var/tmp/inhibitor/%s/kernel' % __version__),
            state       = util.Path('/var/tmp/inhibitor/%s/state'  % __version__),
            share       = util.Path('/usr/share/inhibitor/'),
        )

        for k, v in paths.items():
            if hasattr(self.paths, k):
                setattr(self.paths, k, util.Path(v))
            else:
                util.warn("Ignoring invalid path setting %s" % (k,))

        self.mount_points   = []
        self.children       = []
        self.current_action = None

    def makedirs(self):
        """Create all the directories that may be needed during runtime."""
        for k in self.paths.keys:
            path = getattr(self.paths, k)
            if not os.path.exists(path):
                os.makedirs(path)

        
class Inhibitor(object):
    """
    Holding class for Actions.  Serves to run and track the state
    across multiple actions actions.
    """
    def __init__(self):
        self.actions    = []
        self.state      = InhibitorState()
        self.state.makedirs()

    def add_action(self, action):
        """Add the given action the the run queue."""
        self.actions.insert(0, action)

    def run(self):
        """Run all of the actions on the queue."""
        while len(self.actions) > 0:
            self.run_action(self.actions.pop())

    def run_action(self, action):
        try:
            action.post_conf(self.state)
            action.run()
        except Exception:
            util.umount_all(self.state.mount_points)
            raise


