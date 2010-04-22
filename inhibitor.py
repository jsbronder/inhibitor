import os

import util
from source import InhibitorSource
from actions import CreateSnapshotAction

__version__ = '0.1'

class InhibitorState(object):
    """
    Track the state of the current inhibitor build as well as holding
    the base configuration values.

    @param paths    - Override default paths.
    """
    def __init__(self, paths={}):

        self.paths = util.Container(
            cache       = util.Path('/var/tmp/inhibitor/%s/cache'  % __version__),
            stages      = util.Path('/var/tmp/inhibitor/%s/stages' % __version__),
            build       = util.Path('/var/tmp/inhibitor/%s/build'  % __version__),
            pkgs        = util.Path('/var/tmp/inhibitor/%s/pkgs'   % __version__),
            dist        = util.Path('/var/tmp/inhibitor/%s/dist'   % __version__),
            share       = util.Path(os.path.abspath(os.curdir))
        )

        for k,v in paths.items():
            if hasattr(self.paths, k):
                setattr(self.paths, k, Path(v))
            else:
                warn("Ignoring invalid path setting %s" % (k,))

        self.mount_points   = []
        self.children       = []
        self.current_action = None

    def makedirs(self):
        for k in self.paths.keys:
            path = getattr(self.paths, k)
            if not os.path.exists(path):
                os.makedirs(path)

        
class Inhibitor(object):
    def __init__(self):
        self.actions    = []
        self.state      = InhibitorState()
        self.state.makedirs()

    def add_action(self, action):
        self.actions.insert(0, action)

    def run(self):
        while len(self.actions) > 0:
            self.run_action(self.actions.pop())

    def run_action(self, action):
        try:
            action.post_conf(self.state)
            action.run()
        except Exception, e:
            util.umount_all(self.state.mount_points)
            raise


