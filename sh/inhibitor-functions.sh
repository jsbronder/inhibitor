#!/bin/bash

trap "echo;echo Caught SIGTERM on pid $$;echo;kill -SIGTERM -$$;exit" SIGTERM
trap "echo;echo Caught SIGINT on pid $$ ;echo;kill -SIGINT  -$$;exit" SIGINT

DEBUG=false

_STAR_GREEN="\001\033[0;32m\002*\001\033[0m\002"
_STAR_YELLOW="\001\033[1;33m\002*\001\033[0m\002"
_STAR_RED="\001\033[0;31m\002*\001\033[0m\002"

einfo() {
    echo -e "${_STAR_GREEN} $*"
}

ewarn() {
    echo -e "${_STAR_YELLOW} $*"
}

eerror() {
    echo -e "${_STAR_RED} $*"
}

dot_timer() {
    local i
    local timeout=${1:-1}
    echo

    if ${DEBUG}; then
        einfo "Hit any key to continue"
        read -n 1 -s
    else
        echo -n -e "${_STAR_GREEN} Pausing for $1 second(s): ."
        for ((i=0; i < $1; i++)); do
            echo -n ' .'
            sleep 1
        done
    fi
    echo
}

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
    local i
    local rc
    echo
    einfo "Emerging $*"
    echo
    export EMERGE_WARNING_DELAY=0
    export CLEAN_DELAY=0
    export EBEEP_IGNORE=0
    export EPAUSE_IGNORE=0
    export CONFIG_PROTECT="-*"

    DIE_ON_FAIL=${DIE_ON_FAIL:-1}

    for i in "--pretend --verbose" "--quiet"; do
        emerge ${i} --nospinner --buildpkg --usepkg $*
        rc=$?
        if [ ${rc} -ne 0 ]; then
            if [ ${DIE_ON_FAIL} -eq 0 ]; then
                die "emerge failed"
            else
                return ${rc}
            fi
        fi
        [ "${i}" != "--quiet" ] && dot_timer 5
    done
    return 0
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

get_root() {
    emerge --verbose --info 2>/dev/null | egrep '^ROOT=' | sed 's,ROOT="\([^"]*\)",\1,'
}

#########################################
#   Testing Stage                       #
#########################################
run_generic_stage(){
    echo
    echo "In Generic Stage Chroot!"
    sleep 20
    echo
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
    _run_stage1
}

_run_stage4(){
    local packages="$(</tmp/inhibitor/package_list)"
    local rc=0
    run_emerge --oneshot --newuse virtual/portage
    run_emerge --deep --newuse system
    if [ "${packages}" != "system" ]; then
        run_emerge --deep --newuse ${packages}
    fi
}

run_stage4(){
    _run_stage4
}

