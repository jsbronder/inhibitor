#!/bin/bash

source /tmp/inhibitor/sh/inhibitor-functions.sh || exit 1


install_kernel() {
    local grub_install_hack=false

    ROOT=${KROOT} \
        USE=symlink \
        run_emerge -u --oneshot --nodeps ${KERNEL_PKG}              || die "Failed to emerge ${KERNEL_PKG}"
    pushd "${KROOT}"/usr/src/linux-${KERNEL_RELEASE} &>/dev/null    || die "Failed to cd to kernel source"
    cp ${KERNEL_KCONFIG} .config                                    || die "Failed to copy kconfig"
    einfo "Building kernel"
    make $(portageq envvar / MAKEOPTS)                              || die "Kernel build failed"
    einfo "Installing kernel"

    # mkboot (called by installkernel) likes grub-install to exist.
    # XXX:  Fixed in sys-apps/debianutils-3.1.3
    if [ ! -x /sbin/grub-install ]; then
        touch /sbin/grub-install
        chmod +x /sbin/grub-install
        grub_install_hack=true
    fi

    make INSTALL_PATH=${KROOT}/boot/ install                        || die "Kernel install failed"

    ${grub_install_hack} && rm -f /sbin/grub-install

    ln -snf vmlinuz-${KERNEL_RELEASE} ${KROOT}/boot/kernel
    ln -snf System.map-${KERNEL_RELEASE} ${KROOT}/boot/System.map
    rm -f ${KROOT}/boot/config-${KERNEL_RELEASE}
    einfo "Installing modules"
    make \
        INSTALL_MOD_PATH=${KROOT} \
        modules_install                                             || die "Kernel module install failed"
    popd &>/dev/null
}

post_kern_merge() {
    local rc
    if [ "${POST_KERN_PKGS:0:1}" == "@" ]; then
        POST_KERN_PKGS=""
    fi

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
    local kname=${KPN%-sources*}

    if [ -d /var/db/pkg/sys-kernel/genkernel-[0-9]* ]; then
        rm_genkernel=false
    else
        run_emerge -1 sys-kernel/genkernel
    fi
  
    einfo "Building and installing initramfs"
    /usr/bin/genkernel ${GENKERNEL} \
        --kernname=${KPN%-sources} \
        --kerneldir=${KROOT}/usr/src/linux-${KERNEL_RELEASE} \
        --tempdir=${KCACHE}/gk-tmp \
        --cachedir=${KCACHE}/gk-cache \
        --bootdir=${KROOT}/boot/ \
        --no-mountboot \
        --disklabel \
        initrd  || die "Genkernel failed"

    mv ${KROOT}/boot/initramfs-${kname}-*-${KERNEL_RELEASE} \
       ${KROOT}/boot/initramfs-${KERNEL_RELEASE} \
       || die "Failed to sanitize genkernel intramfs filename"
 
    ln -snf initramfs-${KERNEL_RELEASE} ${KROOT}/boot/initramfs
    ${rm_genkernel} && emerge -C sys-kernel/genkernel
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
    local tarpath=${KCACHE}/${KERNEL_RELEASE}.tar.bz2

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
    local kpkg vers
    
    kpkg=$(portageq best_visible / "${KERNEL_PKG}")
    [ ${?} -eq 0 -a -n "${kpkg}" ] || die "Failed to resolve best_visible ${KERNEL_PKG}"
    vers="$(printf "%s\n%s\n%s\n" \
            "import portage" \
            "a = portage.catpkgsplit('${kpkg}')" \
            "print a[1], a[2], a[3]" | python )"
    KPN=${vers%% *}
    KERNEL_RV=${vers##* }
    KERNEL_V=${vers#* }
    KERNEL_V=${KERNEL_V% *}
    if [ "${KERNEL_RV}" == "r0" ]; then
        KERNEL_RV=""
        KERNEL_RELEASE="${KERNEL_V}-${KPN%-sources}"
    else
        KERNEL_RELEASE="${KERNEL_V}-${KPN%-sources}-${KERNEL_RV}"
    fi

    KROOT="/tmp/inhibitor/kerncache/${KERNEL_RELEASE}/root"
    KCACHE="/tmp/inhibitor/kerncache/${KERNEL_RELEASE}"
    KERNEL_KCONFIG="/tmp/inhibitor/kconfig"
    mkdir -p ${KROOT}/boot \
        ${KCACHE}/gk-tmp \
        ${KCACHE}/gk-cache &>/dev/null
    einfo "Installing ${KERNEL_RELEASE}"
}

install_tarball() {
    einfo "Installing cached kernel package"
    local d=$(get_root)
    tar -xjpf ${KCACHE}/${KERNEL_RELEASE}.tar.bz2 -C ${d} \
        || die "Failed to install kernel tarball"
    if [ -d ${d}usr/src/linux-${KERNEL_RELEASE} ]; then
        pushd ${d}usr/src/linux-${KERNEL_RELEASE} &>/dev/null
        cp ${d}tmp/inhibitor/kconfig .config
        cp ${d}/boot/System.map-${KERNEL_RELEASE} System.map    || die "Failed to copy System.map"
        make modules_prepare                                || die "Failed to make modules_prepare"
        depmod ${KERNEL_RELEASE}                            || die "depmod ${KERNEL_RELEASE} failed"
        popd &>/dev/null
    fi
}

GENKERNEL=""
while [ $# -gt 0 ]; do
    case $1 in
        --kernel_pkg)
            shift;KERNEL_PKG=${1}
            ;;
        --genkernel)
            shift;GENKERNEL=${1}
            ;;
        --packages)
            shift;POST_KERN_PKGS=${1}
            ;;
    esac
    shift
done

if [ -z "${KERNEL_PKG}" ]; then
    die "Kernel Package(--kernel_pkg) must be specified"
fi

init
if ! cached; then
    einfo "No cached kernel build found..."
    install_kernel 
    [ -n "${GENKERNEL}" ] && install_initramfs
    create_tarball
fi
install_tarball
post_kern_merge
