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
    def __init__(self, settings_conf, **keywords):

        self.settings_conf = {
            'base': {
                'required_keys':    ['rootdir'],
                'valid_keys':       ['verbose', 'debug', 'catalyst_support' ],
                'init_args':        {}
            }
        }

        for sc, v in settings_conf.items():
            if sc in self.settings_conf:
                self.settings_conf[sc].required_keys.extend(v['required_keys'])
                self.settings_conf[sc].valid_keys.extend(v['valid_keys'])
                self.settings_conf[sc].init_args.update(v['init_args'])
            else:
                self.settings_conf[sc] = {}
                self.settings_conf[sc].update(v)

        # Create the required dictionaries.
        for s in self.settings_conf:
            tmp = {}
            setattr(self, s, tmp)

        # Fill self.base{}
        self.version = __version__
        self._load_external_settings(**keywords)
        if 'config_file' in keywords:
            self.load_config(keywords['config_file'])

        # Make sure all of our settings make sens.
        self.sanity()

        # Expand from self.base settings.
        self._expand_base_settings()


    def _load_external_settings(self, **keywords):
        """
        Checks the environment for any INHIBITOR_X variables and inserts them
        into the base config.  INHIBITOR_A_B_C=v becomes self.a['b']['c'] = v

        Then checks to see if we were passes a command line.  a.b.c = v becomes
        into self.a['b']['c'] = v

        By default, environment variables are favored over the commandline which
        is favored over any later config file settings.

        Note:  You can only set string values in this way, there is no way to set
        a list or dict or boolean via this method.
        """
       
        # Grab from the environment
        for s in os.environ:
            s = s.lower()
            if s.startswith('inhibitor_'):
                s = s[len('inhibitor_'):].replace('_', '.')
                self._dot_to_dict(s, os.getenv(s))

        # Grab from the command line
        if 'cmdline' in keywords:
            for s in keywords['cmdline']:
                key_val = s.lower().split('=', 1)
                if len(l) == 2:
                    self._dot_to_dict(key_val[0], key_val[1])
     
    def _dot_to_dict(self, keystr, val, overwrite=False):
        """
        Translates keystr=a.b.c and sets self.a['b']['c'] = val
        self.a must already exist and be a dictionary.
        """
        l = keystr.split('.', 1)
        cur = dict = getattr(self, l[0])
        keys = l[1].split('.')
      
        if not dict in self._vs_names:
            raise InhibitorError('Got invalid settings dictionary name %s' % dict)

        unset = False
        for k in keys:
            if not k in dict:
                dict[k] = {}
                cur = dict[k]
                unset = True

        if blank or overwrite:
            cur = val

    def _expand_base_settings(self):
        s = self.base

        self.update_setting( s, 'root', os.path.join(s['rootdir'], self.version))

        dirs =[ 'snapshot_cache',   'snapshots',    'repo_cache',
                'packages',         'builds',       'tmpdir'  ]
        
        for dir in dirs:
            self.update_setting( s, dir, os.path.join(s['root'], dir) )


    def load_config(self, config_file):
        mod = __import__(config_file, globals(), locals())

        for name,v in self.settings_conf.items():
            try:
                f = getattr(mod, name)
            except AttributeError, e:
                raise InhibitorError('Module %s does not have requested target %s: %s'
                    % (config_file, f_name, e))

            new_settings = f(**v['init_args'])
            self.update_values(name, new_settings)

    def update_setting(self, dict, key, value, overwrite=False):
        """
        Optionally set the value in a dictionary to val
        """
        if not overwrite:
            if not key in dict:
                dict[key] = value
        else:
            setattr(dict, key, value) 

  
    def update_values(self, obj_name, new_settings):
        o = getattr(self, obj_name)
        for k,v in new_settings.items():
            self.update_setting(o, k, v)

    def sanity(self):
        sane = True
        
        for name, v in self.settings_conf.items():
            s = getattr(self, name)

            for k in s:
                if not (k in v['valid_keys'] or k in v['required_keys']):
                    err('%s[%s] is not a valid setting' % (name, k))
                    sane = False

            for k in v['required_keys']:
                if not k in s:
                    err('Setting %s[%s] is undefined.' % (name, k))
                    sane = False

        if not sane:
            raise InhibitorError('Bailing out due to invalid settings.')



