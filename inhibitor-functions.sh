#!/bin/bash

if ! source /etc/init.d/functions.sh; then
    echo
    echo "ERROR:  Failed to source /etc/init.d/functions.sh"
    echo
    exit 1
fi

die() {
    echo
    echo -e "\t\001\033[0;31m\002*\001\033[0m\002 Inhibitor error in chroot"
    echo -e "\t\001\033[0;31m\002*\001\033[0m\002 $*"
    echo
    exit 1
}

_init() {
    /usr/sbin/env-update || die 'env-update failed'
    source /etc/profile || die 'sourcing /etc/profile failed'
}
init() {
    _init
}

_run_emerge() {
    einfo "Emerging $*"
    export EMERGE_WARNING_DELAY=0
    export CLEAN_DELAY=0
    export EBEEP_IGNORE=0
    export EPAUSE_IGNORE=0
    export CONFIG_PROTECT="-*"
    export PKGDIR=/tmp/inhibitor/packages

    emerge --buildpkg --usepkg $* || die "emerge failed"
}
run_emerge() {
    _run_emerge $*
}

source_wrapper() {
    for f in $*; do
        if ! source /tmp/${f}; then
            die "Failed to source $(pwd)/${f}"
        fi
    done
}


#########################################
#   Stage 1                             #
#########################################

# Snagged from Catalyst
_get_stage1_packages() {
    python <<-"EOF"
#!/usr/bin/python

import os,portage,sys

# this loads files from the profiles ...
# wrap it here to take care of the different
# ways portage handles stacked profiles
# last case is for portage-2.1_pre*
def scan_profile(file):
    if "grab_stacked" in dir(portage):
        return portage.grab_stacked(file, portage.settings.profiles, portage.grabfile, incremental_lines=1);
    else:
        if "grab_multiple" in dir(portage):
            return portage.stack_lists( portage.grab_multiple(file, portage.settings.profiles, portage.grabfile), incremental=1);
        else:
            return portage.stack_lists( [portage.grabfile_package(os.path.join(x, file)) for x in portage.settings.profiles], incremental=1);

# loaded the stacked packages / packages.build files
pkgs = scan_profile("packages")
buildpkgs = scan_profile("packages.build")

# go through the packages list and strip off all the
# crap to get just the <category>/<package> ... then
# search the buildpkg list for it ... if it's found,
# we replace the buildpkg item with the one in the
# system profile (it may have <,>,=,etc... operators
# and version numbers)
for idx in range(0, len(pkgs)):
    try:
        bidx = buildpkgs.index(portage.dep_getkey(pkgs[idx]))
        buildpkgs[bidx] = pkgs[idx]
        if buildpkgs[bidx][0:1] == "*":
            buildpkgs[bidx] = buildpkgs[bidx][1:]
    except: pass

for b in buildpkgs: sys.stdout.write(b+" ")
EOF
}

get_stage1_packages(){
    _get_stage1_packages
}

_setup_stage1_environment(){
    export USE="-* bindist build $(portageq envvar STAGE1_USE)"
    export FEATURES="nodoc noman noinfo"
    export ROOT=/tmp/stage1root
}
setup_stage1_environment(){
    _setup_stage1_environment
}

_run_stage1(){
    local packages="$(get_stage1_packages)"

    setup_stage1_environment
    mkdir -p ${ROOT}

    if [ -z "${packages}" ]; then
        die "Stage1 package list is empty."
    else
        echo "Stage1 packages:  ${packages}"
    fi

    run_emerge --nodeps --oneshot sys-apps/baselayout 
    run_emerge --oneshot ${packages}
}
run_stage1(){
    init
    _run_stage1
}



