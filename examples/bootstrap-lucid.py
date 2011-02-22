import sys
import os
import inhibitor

stageconf = inhibitor.Container(
    name            = 'example-deb-stage1',
    suite           = 'lucid',
    mirror          = 'http://ubuntu.media.mit.edu/ubuntu/',
    arch            = 'i386',
)

def main():
    top_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[0]))),
        'sh')
    resume = True
    if '-f' in sys.argv:
        resume = False
    i = inhibitor.Inhibitor(paths={'share':top_dir})
    s = inhibitor.DebootstrapStage(stageconf, 'example', resume=resume)
    i.add_action(s)
    i.run()

if __name__ == '__main__':
    main()


