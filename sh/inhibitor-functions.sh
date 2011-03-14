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

deb_disable_init() {
    local replace="start-stop-daemon initctl init"
    for f in ${replace}; do
        if [ -x /sbin/${f} ]; then
            mv /sbin/${f}{,-bkup}
            printf "%s\n%s\n" \
                "#!/bin/sh" \
                "echo '$f disabled during non-interactive build'" \
                > /sbin/${f}
            chmod 755 /sbin/${f}
        fi
    done
}

deb_enable_init() {
    local replace="start-stop-daemon initctl init"
    for f in ${replace}; do
        if [ -x /sbin/${f}-bkup ]; then
            mv /sbin/${f}{-bkup,}
        fi
    done
}

_init() {
    if [ -x /usr/sbin/env-update ]; then
        /usr/sbin/env-update || die 'env-update failed'
    elif [ -x /sbin/ldconfig ]; then
        /sbin/ldconfig
    fi
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

_run_apt_install() {
    echo
    einfo "Apt-get installing $*"
    echo
    
    export LC_ALL=C
    export DEBIAN_FRONTEND='noninteractive'
    export PATH

    DIE_ON_FAIL=${DIE_ON_FAIL:-1}
    deb_disable_init
    apt-get install --assume-yes --force-yes \
        --no-install-recommends --auto-remove \
        $*
    rc=$?
    deb_enable_init
    if [ ${rc} -ne 0 ]; then
        if [ ${DIE_ON_FAIL} -eq 0 ]; then
            die "apt-get install failed"
        else
            return ${rc}
        fi
    fi
    return 0
}
run_apt_install() {
    _run_apt_install $*
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

