import sys
import os
import inhibitor

def get_sources_list(**keywds):
    url = 'http://ubuntu.media.mit.edu/ubuntu'
    components = 'main restricted universe multiverse'
    ret = ''
    for dist in ('lucid', 'lucid-updates', 'lucid-security'):
        ret += 'deb %s %s %s\n' % (url, dist, components)
        ret += 'deb-src %s %s %s\n' % (url, dist, components)
        ret += '\n'
    return ret

my_packages = [
    'sudo', 'rsyslog', 'dhcp3-client', 'ntp', 'ntpdate',
    'cron', 'screen', 'vim', 'linux-generic'
]

stageconf = inhibitor.Container(
    name            = 'example-lucid',
    suite           = 'lucid',
    mirror          = 'http://ubuntu.media.mit.edu/ubuntu/',
    arch            = 'i386',
    sources_list    = inhibitor.create_source(get_sources_list),
    seed            = 'debstage1-example',
    packages        = my_packages,
)

def main():
    top_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[0]))),
        'sh')
    resume = True
    if '-f' in sys.argv:
        resume = False
    i = inhibitor.Inhibitor(paths={'share':top_dir})
    s = inhibitor.DebianStage(stageconf, 'example', resume=resume)
    i.add_action(s)
    i.run()

if __name__ == '__main__':
    main()


