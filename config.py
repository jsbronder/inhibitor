inhibitor_settings_map = [
    ('inhibitor_settings',      'base'),
    ('snapshot_settings',       'snapshot')
]

inhibitor_settings = {
    'root':             '/var/tmp/catalyst/0.8',
    'snapshot_cache':   '/var/tmp/catalyst/0.8/snapshot_cache',
    'snapshots':        '/var/tmp/catalyst/0.8/snapshots',
    'repo_cache':       '/var/tmp/catalyst/0.8/inhibitor/repo_cache/'
}


snapshot_settings = {
    'brontes3d':{
        'type': 'git',
        'src':  'git://lex-bs.mmm.com/portage-overlay.git'
    }
}
