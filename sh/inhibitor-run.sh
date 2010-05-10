#!/bin/bash
cd /tmp/inhibitor/sh

if ! source ./inhibitor-functions.sh; then
    echo
    echo 'ERROR:  Cannot source inhibitor-functions.sh'
    echo
    exit 1
fi

init
$*
