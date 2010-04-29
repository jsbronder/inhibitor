#!/bin/bash

source /tmp/inhibitor/sh/inhibitor-functions.sh || exit 1


install_kernel() {
    ROOT=${KROOT} \
        USE=symlink \
        run_emerge -u --oneshot --nodeps ${KERNEL_PKG}
    pushd "${KROOT}"/usr/src/linux-${KERNEL_RELEASE} &>/dev/null    || die "Failed to cd to kernel source"
    cp ${KERNEL_KCONFIG} .config                                    || die "Failed to copy kconfig"
    einfo "Building kernel"
    make $(portageq envvar / MAKEOPTS)                              || die "Kernel build failed"
    einfo "Installing kernel"

    which grub-install
    ls -l /sbin/grub-install
    echo $PATH
    make INSTALL_PATH=${KROOT}/boot/ install                        || die "Kernel install failed"

    ln -snf vmlinuz-${KERNEL_RELEASE} ${KROOT}/boot/kernel
    ln -snf System.map-${KERNEL_RELEASE} ${KROOT}/boot/System.map
    rm -f ${KROOT}/boot/config-${KERNEL_RELEASE}
    einfo "Installing modules"
    # To make sure that depmod doesn't run as it will fail due
    # to the use of a non-standard MODLIB
    mv System.map{,.bkup}
#        MODLIB=${KROOT}/lib/modules/${KERNEL_RELEASE} \
    make \
        INSTALL_MOD_PATH=${KROOT} \
        modules_install                                             || die "Kernel module install failed"
    mv System.map{.bkup,}
    popd &>/dev/null
}

post_kern_merge() {
    local rc
    if [ "${POST_KERN_PKGS:0:1}" == "@" ]; then
        POST_KERN_PKGS=""
    fi

    for i in ${GK_ARGS}; do
        case "${i}" in
            --splash=*)
                POST_KERN_PKGS="${POST_KERN_PKGS} media-gfx/splashutils"
                ;;
            *)
                ;;
        esac
    done

    if [ -z "${POST_KERN_PKGS}" ]; then
        return
    fi
  
    mkdir -p /etc/portage/profile/ &>/dev/null
    echo 'sys-kernel/gentoo-sources-99' >> /etc/portage/profile/package.provided
    local old_sym=$(readlink /usr/src/linux)

    einfo "Installing post kernel build packages"
    ln -snf ${KROOT}/usr/src/linux-${KERNEL_RELEASE} /usr/src/linux 
    DIE_ON_FAIL=0 run_emerge -u ${POST_KERN_PKGS}
    rc=$?
    
    if [ -z "${old_sym}" ]; then
        rm /usr/src/linux
    else
        ln -snf ${old_sym} /usr/src/linux
    fi

    sed -i '/sys-kernel\/gentoo-sources-99/d' /etc/portage/profile/package.provided
    [ -s /etc/portage/profile/package.provided ] \
        || rm -f /etc/portage/profile/package.provided
    rmdir /etc/portage/profile/package.provided/ &>/dev/null

    if [ ${rc} -ne 0 ]; then
        die "emerge failed."
    fi
}
    
install_initramfs() {
    local rm_genkernel=true
    local kname=${KPN%-sources-*}

    if [ -d /var/db/pkg/sys-kernel/genkernel-[0-9]* ]; then
        rm_genkernel=false
    else
        run_emerge -1 sys-kernel/genkernel
    fi
  
    einfo "Building and installing initramfs"
    /usr/bin/genkernel ${GK_ARGS} \
        --kernname=${KPN%-sources-*} \
        --kerneldir=${KROOT}/usr/src/linux-${KERNEL_RELEASE} \
        --tempdir=${KCACHE}/gk-tmp \
        --cachedir=${KCACHE}/gk-cache \
        --bootdir=${KROOT}/boot/ \
        --no-mountboot \
        --disklabel \
        --mdadm \
        initrd  || die "Genkernel failed"

    mv ${KROOT}/boot/initramfs-${kname}-*-${KERNEL_RELEASE} \
       ${KROOT}/boot/initramfs-${KERNEL_RELEASE} \
       || die "Failed to sanitize genkernel intramfs filename"
 
    ln -snf initramfs-${KERNEL_RELEASE} ${KROOT}/boot/initramfs
}

create_tarball() {
    einfo "Creating kernel cache tarball"
    pushd ${KROOT} &>/dev/null || die "Failed to cd to fakeroot"
    tar -cjpf ${KCACHE}/${KERNEL_RELEASE}.tar.bz2 \
        etc/ boot/ lib*/ || die "Failed to compress kernel package"
    popd &>/dev/null
    cp ${KERNEL_KCONFIG} ${KCACHE}/kconfig
    sha512sum ${KCACHE}/${KERNEL_RELEASE}.tar.bz2 \
        | cut -d' ' -f 1 \
        > ${KCACHE}/tarhash
}

cached() {
    local tarpath=${KCACHE}/${KPN}.tar.bz2

    [ -f ${KCACHE}/kconfig ] || return 1
    cmp ${KERNEL_KCONFIG} ${KCACHE}/kconfig \
        &>/dev/null || return 1

    [ -f ${KCACHE}/tarhash ] || return 1
    
    [ -f ${tarpath} ] || return 1

    sha512sum ${tarpath} \
        | cut -d' ' -f 1 \
        > ${KROOT}/.newhash
    cmp ${KROOT}/.newhash ${KCACHE}/tarhash &>/dev/null
}

init() {
    _init
    einfo "Preparing to build and install the kernel"
    local vers="$(printf "%s\n%s\n%s\n" \
            "import portage" \
            "a = portage.catpkgsplit('${KERNEL_PKG}')" \
            "print a[2], a[3]" | python )"
    KERNEL_V=${vers% *}
    KERNEL_RV=${vers#* }
    KPN=${KERNEL_PKG#*/}
    if [ "${KERNEL_RV}" == "r0" ]; then
        KERNEL_RV=""
        KERNEL_RELEASE="${KERNEL_V}-${KPN%-sources-*}"
    else
        KERNEL_RELEASE="${KERNEL_V}-${KPN%-sources-*}-${KERNEL_RV}"
    fi

    KROOT="/tmp/inhibitor/kerncache/${BUILD_NAME}/${KERNEL_RELEASE}/root"
    KCACHE="/tmp/inhibitor/kerncache/${BUILD_NAME}/${KERNEL_RELEASE}"
    KERNEL_KCONFIG="/tmp/inhibitor/kconfig"
    mkdir -p ${KROOT}/boot \
        ${KCACHE}/gk-tmp \
        ${KCACHE}/gk-cache &>/dev/null
    einfo "Installing ${KERNEL_RELEASE} for ${BUILD_NAME}"
}

install_tarball() {
    einfo "Installing cached kernel package"
    tar -xjpf ${KCACHE}/${KERNEL_RELEASE}.tar.bz2 -C / \
        || die "Failed to install kernel tarball"
}

while [ $# -gt 0 ]; do
    case $1 in
        --build_name)
            shift;BUILD_NAME=${1}
            ;;
        --kernel_pkg)
            shift;KERNEL_PKG=${1}
            ;;
        --gk_args)
            shift;GK_ARGS=${1}
            ;;
        --packages)
            shift;POST_KERN_PKGS=${1}
            ;;
    esac
    shift
done

if [ -z "${BUILD_NAME}" -o -z "${KERNEL_PKG}" ]; then
    die "Both --build_name and --kernel_pkg must be specified"
fi

init
if ! cached; then
    einfo "No cached kernel build found..."
    install_kernel 
    post_kern_merge
    install_initramfs
    create_tarball
fi
install_tarball
