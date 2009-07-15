import types
import re
import shutil

from base_funcs import *

__version__ = '0.8'
__package__ = 'inhibitor'
__prefix__  = os.getcwd()

class InhibitorObject(object):
    """
    This is a blank class for now, although it can be expanded in the future.

    TODO:
        -Loading arguments from the command line. a.b.c = d => settings[a][b][c] = d
        -Return class specific settings rather then everything.

    Default preference order is environment > command line > keywords > settings
    """
    def __init__(self,
        settings_conf,
        actions={},
        settings_override={},
        cmdline={},
        config_file=None,
        **keywords):

        self.actions = actions

        self.settings_conf = {
            'base': {
                'required_keys':    ['rootdir', 'installdir'],
                'valid_keys':       ['verbose',     'debug',        'catalyst_support',
                                    'force',        'tmp',          'stage_cache',
                                    'root',         'snapshots',    'snapshot_cache',
                                    'builds',       'repo_cache',   'packages',
                                    'quiet'],
                'config_init':      {},
            }
        }

        for sc, v in settings_conf.items():
            if sc in self.settings_conf:
                self.settings_conf[sc]['required_keys'].extend(v['required_keys'])
                self.settings_conf[sc]['valid_keys'].extend(v['valid_keys'])
                self.settings_conf[sc]['config_init'].update(v['config_init'])
            else:
                self.settings_conf[sc] = {}
                self.settings_conf[sc].update(v)
            self.settings_conf[sc]['config_init'].update(cmdline)


        self.version = __version__

        # If we were passed any settings, assume they've already been
        # parsed, validated and expanded.
        for setting, value in settings_override.items():
            if setting in self.settings_conf:
                tmp = {}
                tmp.update(value)
                setattr(self, setting, tmp)
            else:
                raise InhibitorError(
                    'Passed %s in settings_override, but it is not a valid dictionary'
                    % setting)

        load_list = []
        for setting, value in self.settings_conf.items():
            if hasattr(self, setting):
                dbg('Settings for %s handed in from child class' % setting)
                continue
            else:
                tmp = {}
                setattr(self, setting, tmp)
                load_list.append(setting)
        
        self._load_external_settings(load_list, cmdline)

        if config_file:
            self.config_file = config_file
            self.load_config(config_file, load_list)
        
        # Expand from self.base settings.
        self.expand_base_settings(**keywords)

        # Make sure all of our settings make sens.
        if 'base' in load_list:
            self.sanity(check_list=['base'])

    def _load_external_settings(self, load_list, cmdline):
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
                self._dot_to_dict(s, os.getenv(s), load_list=load_list)

        # Grab from the command line
        for key,val in cmdline.items():
            if key in self.settings_conf:
                self.update_setting(key,val)
                
    def _dot_to_dict(self, keystr, val, overwrite=False, load_list=[]):
        """
        Translates keystr=a.b.c and sets self.a['b']['c'] = val
        self.a must already exist and be a dictionary.
        """
        l = keystr.split('.', 1)
        dict = getattr(self, l[0])
        keys = l[1].split('.')

        if not l[0] in self.settings_conf:
            raise InhibitorError('Got invalid settings dictionary name %s' % dict)

        if len(load_list) > 0 and not l[0] in load_list:
            dbg('Ignoring setting setting %s=%s, %s already loaded by child.'
                % (keystr, val, dict))
            return

        for k in keys:
            if not k in dict or overwrite:
                dict[k] = val

    def expand_base_settings(self, **keywords):
        s = self.base

        for k in ['verbose', 'force', 'debug', 'quiet' ]:
            if not k in s:
                s[k] = k in keywords and keywords[k] or False

        global inhibitor_debug
        inhibitor_debug = s['debug']

        self.update_setting(s, 'root', os.path.join(s['rootdir'], self.version))
        self.update_setting(s, 'installdir', os.getcwd())

        dirs =[ 'snapshot_cache',   'snapshots',    'repo_cache',
                'packages',         'builds',       'tmp',
                'stage_cache' ]
        
        for dir in dirs:
            targ = path_join(s['root'], dir) 
            self.update_setting( s, dir, targ )
            if not os.path.isdir(targ):
                if os.path.exists(targ):
                    raise InhibitorError('%s is not a directory, removing' % targ)
                os.makedirs(targ)

    def load_config(self, config_file, load_list):
        mod = __import__(config_file.rstrip('.py'), globals(), locals())
        for name,v in self.settings_conf.items():
            if not name in load_list:
                continue
            try:
                f = getattr(mod, name)
            except AttributeError, e:
                raise InhibitorError('Module %s does not have requested target %s: %s'
                    % (config_file, f_name, e))
            
            dbg('Calling %s.%s with %s' % (config_file, name, v['config_init']))
            new_settings = f(**v['config_init'])
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

    def sanity(self, check_list=[]):
        sane = True
        
        for name, v in self.settings_conf.items():
            if len(check_list) > 0 and not name in check_list:
                continue

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

    def run_action(self, action):
        if not action in self.actions:
            raise InhibitorError('Undefined action name: %s' % action)
        
        function_list = []
        for func_name in self.actions[action]:
            if not hasattr(self, func_name):
                raise InhibitorError('Undefined function %s for action %s' % (func_name, action))
            f = getattr(self, func_name)
            if not type(f) == types.MethodType:
                raise InhibitorError('In action %s, name %s is not a function' % (action, func_name))
            function_list.append(f)

        id = hasattr(self, 'name') and getattr(self, 'name') or None
        if id == None:
            warn('No identifier found for this action, resume will not be supported.')
        else:
            status_dir = path_join(self.base['tmp'], 'status', id)
            if self.base['force']:
                warn('Force enabled, cleaning status files')
                if os.path.exists(status_dir):
                    shutil.rmtree(status_dir)
            if not os.path.isdir(status_dir):
                os.makedirs(status_dir)

        for i in range(0, len(function_list)):
            if id:
                status_file = path_join(status_dir, action + '-' + self.actions[action][i])
                if os.path.exists(status_file):
                    warn('Resume:  Skipping previously completed %s step' % self.actions[action][i])
                    continue
            try:
                function_list[i]()
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception, e:
                import traceback
                print '---------------------------------------------------'
                traceback.print_exc()
                print '---------------------------------------------------'
                raise InhibitorError('Exception during action %s, function %s.'
                    % (action, self.actions[action][i]))

            if id:
                open(status_file, 'w').close()

        if id:
            shutil.rmtree(status_dir)



