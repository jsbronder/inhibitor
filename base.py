import types

from base_funcs import *

class InhibitorObject(object):
    def __init__(self, settings_file=None):
        self.settings = {}
        if settings_file:
            self._load_settings_file(settings_file)

    def _load_settings_file(self, file):
        valid_settings = [
            'base',             # Global configuration.
            'snapshot',         # Snapshot definitions.
        ]

        try:
            mod = __import__(file, globals(), locals())
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception, e:
            InhibitorError("Failed to import '%s': %s" % (file, e))
       
        print mod.inhibitor_settings_map
        if not hasattr(mod, 'inhibitor_settings_map'):
            InhibitorError("%s does not contain 'inhibitor_settings_map'" % mod.__name__)

        map = mod.inhibitor_settings_map
        if not type(map) == types.ListType:
            InhibitorError("%s.inhibitor_settings_map is not a list" % mod.__name__)

        for n, s in map:
            if not s in valid_settings:
                InhibitorError("%s refers to invalid setting '%s'" % (mod.__name__, s))
            dict = getattr(mod, n)
            if not type(dict) == types.DictType:
                InhibitorError("%s.%s is not a dictionary." % (mod.__name__, n))
            self.settings[s] = dict
