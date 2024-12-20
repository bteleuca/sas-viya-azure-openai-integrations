SAS_config_names=['httpsviya']

SAS_config_options = {'lock_down': False,
                      'verbose'  : True,
                      'prompt'   : True
                     }

SAS_output_options = {'output' : 'html5'}       # not required unless changing any of the default

httpsviya = {'url' : 'your-sas-viya-url.com',
             'context' : 'SAS Studio compute context',
             'options' : ["fullstimer", "memsize=4G"],
             'verify' : False
             }