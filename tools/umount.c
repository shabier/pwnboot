// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 shabier and the pwnboot contributors.
/*
 * Minimal `umount` for the Legacy-iOS-Kit SSH ramdisk, which has no
 * umount(8). Calls the unmount(2) syscall with MNT_FORCE.
 *
 * Useful when you've mounted the data partition (e.g. via /bin/mount.sh)
 * and need to free /dev/disk0sNsM for raw `dd` access, since iOS rejects
 * raw block reads of a CP partition while it's mounted.
 *
 * Build:
 *   clang -arch armv7 -isysroot iPhoneOS.sdk -miphoneos-version-min=6.0 \
 *         -Wl,-no_pie -Wl,-e,_start -o umount start.S umount.c
 *   python3 lc_main_to_unixthread.py umount umount-fixed
 *   ldid -S umount-fixed
 *
 * Usage on the iPod (after scp'ing umount-fixed in):
 *   /var/root/umount /mnt2
 */
#include <unistd.h>
#include <sys/mount.h>
#include <stdio.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <mountpoint>\n", argv[0]);
        return 1;
    }
    if (unmount(argv[1], MNT_FORCE) < 0) {
        fprintf(stderr, "unmount %s failed: errno=%d\n", argv[1], errno);
        return 1;
    }
    printf("unmounted %s\n", argv[1]);
    return 0;
}
