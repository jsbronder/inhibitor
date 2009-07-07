import types
import re

from base_funcs import *

__version__ = '0.8'
__package__ = 'inhibitor'

class InhibitorObject(object):
    """
    This is a blank class for now, although it can be expanded in the future.

    TODO:
        -Loading arguments from the command line. a.b.c = d => settings[a][b][c] = d
        -Return class specific settings rather then everything.

    Default preference order is environment > command line > keywords > settings
    """
    def __init__(self, cmdline = [], **keywords):

        self.settings = {}
        self.settings['base'] = {}

        self._load_env_settings()
        self._load_cmdline_settings(cmdline)
        self._load_base_settings()

        self.verbose = False
        self.force = False
        for k,v in keywords.items():
            setattr(self, k, v)


    def sanity_check(self, required_vars):
        for var in required_vars:
            cur = self.settings
            keylist = var.split('.')
            for i in range(0, len(keylist)):
                try:
                    a = cur
                except KeyError:
                    raise InhibitorError("Missing settings:  '%s' required but '%s' is undefined."
                        % (var, keylist[:i]))

    def load_config(self, type, config_file):
        mod = __import__(config_file, globals(), locals())
        f = getattr(mod, type)
        f(self.settings)

    def set_kstr_v(self, keystr, val, overwrite=False):
        """
        Given a dot (.) seperated value that reflects a path in self.settings,
        optionally create the required dictionaries and update the value.
        keystr='a.b.c' => self.settings['a']['b']['c']
        """
        keystr = keystr.strip().lower()
        val = val.strip().lower()
        cur = self.settings
        for v in keystr.split('.'):
            if not (cur and type(cur) == types.TypeDict):
                cur = {}
                cur = cur[v]

        if not overwrite:
            try:
                a = cur
            except KeyError:
                cur = val
        else:
            cur = val

    def set_kv(self, dict, key, value, overwrite=False):
        """
        Optionally set the value in a dictionary to val
        """
        if not overwrite:
            if not hasattr(dict, key):
                dict[key] = value
        else:
            setattr(dict, key, value) 


    def _load_cmdline_settings(self, cmdline):
        """
        The default parses the commandline looking for key=value statements.

        This is a really quick and stupid parser.  Anything up to = is considered
        to be the key, anything after is the value.  Values can be contained within
        quotes which will be stripped.
        """
        for s in cmdline:
            l = s.lower().split('=', 1)
            if len(l) == 2:
                self.set_kstr_v(k, l[1])

    def _load_env_settings(self):
        for s in os.environ:
            if s.lower().startswith('inhibitor_'):
                self.set_kstr_v( s[len('inhibitor_'):], os.getenv(s))
    
    def _load_base_settings(self):
        s = self.settings['base']

        self.set_kv( s, 'version', __version__ )
        self.set_kv( s, 'root', os.path.join('/var/tmp/inhibitor', __version__))
        self.set_kv( s, 'catalyst_support', False)

        root = s['root']

        dirs =[ 'snapshot_cache',   'snapshots',    'repo_cache',
                'packages',         'builds' ]

        for dir in dirs:
            self.set_kv( s, dir, os.path.join(root, dir) )
            
    

    def _load_stage_settings(self, **keywords):
        d = {}

        if not 'subarch' in keywords:
            raise InhibitorError('subarch must be defined for stage runs')

        # Specfile settings
        sf = {}
        sf['subarch']       = keywords['subarch']
        sf['rel_type']      = 'rel_type' in keywords and keywords['rel_type'] or 'default'
        sf['version_stamp'] = self.build_name

        # The following are set at stage runtime to various defaults.
        sf['snapshot']          = None
        sf['source_subpath']    = None
        sf['pkgcache_path']     = None

        d['specfile'] = sf
        d['portage_conf']   = None
        d['catalyst_env']   = None
      
        r['global']['subarch'] = keywords['subarch']
        r['global']['rel_type'] = 'rel_type' in keywords and keywords['rel_type'] or 'default'
        r['global']['version_stamp'] = self.build_name

        pkgcache_root = os.path.join(self.settings['base']['pkgcache_root'], r['global']['rel_type'])
        for i in range(1,4):
            r['stage'+i]['pkgcache_path'] = os.path.join(
                pkgcache_root,
                self.build_name+'-stage%d' % i)

        builds_root = os.path.join(self.settings['base']['builds'], r['global']['rel_type'])
        for i in range(2,4):
            r['stage'+i]['source_subpath'] = os.path.join(
                builds_root,
                self.build_name+'-stage%d' % (i-1))

        return r
