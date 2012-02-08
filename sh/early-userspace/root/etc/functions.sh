#!/bin/sh

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

die() {
    echo
    eerror "$*"
    exit 1
}

die_shutdown () {
    echo
    eerror "$*"
    echo
    echo "Hit 'y' to shutdown."
    echo
    while true; do
        read -n1 resp
        if [ "${resp}" == "y" -o "${resp}" == "Y" ]; then
            /sbin/shutdown -h now
        fi
    done
}

find_drive_by_label () {
    for i in $(blkid 2>&1 | grep LABEL= | sed 's,\([^:]*\).*LABEL="\([^"]*\).*,\1:\2,'); do
        [ "${i#*:}" == "${1}" ] && echo ${i%:*} && return 0
    done
    return 1
}

mount_at () {
    local dir drive
    dir=${1}
    drive=${2}
    shift;shift

    [ -d ${dir} ] || mkdir -p ${dir}

    if ! mount $* ${drive} ${dir}; then
        eerror "Failed to mount ${drive} at ${dir} (options: ${*})"
        return 1
    fi
}

umount_hard () {
    local dev path m failed
    local paths=""
    local rc=0


    for m in $(cat /proc/mounts); do
        [ ${m:0:1} == "/" ] || continue
        dev=${m%% *}
        path=$(echo $m | cut -d' ' -f2)

        if [ "$dev" == "$1" -o "$path" == "$1" ]; then
            paths="${path} ${paths}"
        fi
    done

    for m in ${paths}; do
        if ! umount -f ${m}; then
            ewarn "Failed to umount ${1}."
            for p in /proc/[0-9]*; do
                cwd=$(readlink ${p}/cwd)
                if [ "${cwd:0:${#m}}" == "${m}" ]; then
                    kill ${p#/proc}
                fi
            done
            if ! umount -f ${m}; then
                eerror "Failed to umount ${1} after killing processes, giving up."
                rc=1
            fi
        fi
    done
    return ${rc}
}

loop () {
    local max=${1}
    local action=${2}
    local errmsg=${3}
    local n=0

    while [ ${n} -lt ${max} ]; do
        ${action} && return 0
        [ -n "${errmsg}" ] && ewarn $(printf ${errmsg} ${n} ${max})
        sleep 1
        n=$((n+1))
    done

    return 1
}












