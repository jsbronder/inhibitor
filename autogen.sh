#!/bin/sh
[ ! -d build-aux ] && mkdir build-aux 
aclocal -I m4/ || exit
autoconf || exit
automake -a -c || exit
