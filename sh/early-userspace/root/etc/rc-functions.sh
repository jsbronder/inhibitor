#!/bin/sh
SCRIPTNAME=${1##*/}
SCRIPTNAME=${SCRIPTNAME#[KS][0-9][0-9]}

start   () { return 0; }
stop    () { return 0; }
restart () { start && stop; }

die () {
    echo "ERROR:  $*"
    if [ -x /usr/bin/logger ]; then
        /usr/bin/logger -s -t ${SCRIPTNAME} "$*"
    fi
    exit 1
}

function_init () {
    if [ -f /etc/conf.d/${SCRIPTNAME} ]; then
        source /etc/conf.d/${SCRIPTNAME}
    fi
    source /etc/init.d/${SCRIPTNAME}
}

run_script() {
    echo -n "$1 ${SCRIPTNAME}...  "
    if $2; then
        echo "Success"
    else
        echo "Failure"
    fi
}

enable() {
    if [ -n "${START}" ]; then
        ln -s ../init.d/${SCRIPTNAME} /etc/rc.d/S${START}${SCRIPTNAME}
    fi

    if [ -n "${STOP}" ]; then
        ln -s ../init.d/${SCRIPTNAME} /etc/rc.d/K${STOP}${SCRIPTNAME}
    fi
}

disable() {
    if [ -n "${START}" ]; then
        rm -f /etc/rc.d/S${START}${SCRIPTNAME}
    fi

    if [ -n "${STOP}" ]; then
        rm -f /etc/rc.d/K${STOP}${SCRIPTNAME}
    fi
}

function_init
case "$2" in
    start)
        run_script "Starting" start;;
    stop)
        run_script "Stopping" stop;;
    restart)
        run_script "Restarting" restart;;
    enable)
        enable;;
    disable)
        disable;;
esac
