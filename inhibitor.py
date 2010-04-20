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




act = {
    'action':   'mksnapshot',
    'src':      InhibitorSource('git://lex-bs.mmm.com/portage-overlay',
        name='brontes3d',
        rev='restorative-2.0.3_p5')
}

def etc_portage(conf):
    ret = {}
    ret['package.mask'] = """
        # Py_NONE gets decreffed once to many times
        >=dev-python/numarray-1.4
        # Moves wpa_cli, Brontes bug #4270
        >net-wireless/wpa_supplicant-0.6
        # Does not install libwfb.so, required for older xorg-xserver
        >=x11-drivers/nvidia-drivers-190
        """
    ret['package.keywords'] = {}
    ret['package.keywords']['base'] = """
        # EAPI 2
        =sys-apps/portage-2.1.6*
        """
    ret['package.keywords']['devmode'] = """
        # Nvidia
        =x11-drivers/nvidia-drivers-185*
        media-video/nvidia-settings
        """
    return ret

tds = InhibitorSource(etc_portage)


def main():
    util.INHIBITOR_DEBUG = True
    i = Inhibitor()
    action = CreateSnapshotAction(act['src'])
    i.run_action(action)
    action = CreateSnapshotAction(tds)
    i.run_action(action)



if __name__ == '__main__':
    main()
