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
    def __init__(self, 
        required_settings = [], valid_settings = [],
        **keywords):

        self.required_settings = [ 
            ('base',        ['rootdir'],  {}) 
        ]

        self.valid_settings = [
            ('base',        ['verbose', 'debug' ], {})
        ]
       
        self.required_settings.extend(required_settings)
        self.valid_settings.extend(valid_settings)
       
        # Create the required dictionaries.
        for tup in self.valid_settings:
            tmp = {}
            setattr(self, tup[0], tmp)

       
        # Fill self.base{}
        self.base['version'] = __version__
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
     
        for k,v in keywords.items():
            for name, keys, _ in self.valid_settings:
                if k in keys:
                    d = getattr(self, name)
                    d[k] = v

    def _dot_to_dict(self, keystr, val, overwrite=False):
        """
        Translates keystr=a.b.c and sets self.a['b']['c'] = val
        self.a must already exist and be a dictionary.
        """
        l = keystr.split('.', 1)
        cur = dict = getattr(self, l[0])
        keys = l[1].split('.')
       
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

        self.update_setting( s, 'root', os.path.join(s['rootdir'], __version__))

        dirs =[ 'snapshot_cache',   'snapshots',    'repo_cache',
                'packages',         'builds',       'tmpdir'  ]
        
        for dir in dirs:
            self.update_setting( s, dir, os.path.join(s['root'], dir) )


    def load_config(self, config_file):
        mod = __import__(config_file, globals(), locals())

        for f_name,_,keywords in self.valid_settings:
            try:
                f = getattr(mod, f_name)
            except AttributeError, e:
                raise InhibitorError('Module %s does not have requested target %s: %s'
                    % (config_file, f_name, e))

            new_settings = f(**keywords)

            self.update_values(f_name, new_settings)

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
        for k,v,_ in self.required_settings:
            try:
                o = getattr(self, k)
            except AttributeError:
                raise InhibitorError('Settings for %s are undefined.' % k)
            for key in v:
                if not key in o:
                    raise InhibitorError('Setting %s in %s is undefined.' % (v, k))



