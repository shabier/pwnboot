#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 shabier and the pwnboot contributors.
"""
Offline kernelcache patcher for Sogeti's IOAESAccelerator UID patch.

Sogeti's `iphone-dataprotection/ramdisk_tools/kernel_patcher.c` was designed
to patch the running kernel from userspace via `task_for_pid(0)` + `vm_write`.
That requires TFP0, which itself is a kernel patch we don't have, so it's
chicken-and-egg.

This script applies the exact same patch *offline* to an encrypted iOS
kernelcache (img3 format), bypassing the TFP0 requirement. The result is
ready to be packed into a Legacy-iOS-Kit SSH ramdisk and booted.

The patch:
    Search:  67 D0 40 F6     (a MOVW instruction in IOAESAccelerator's
                              entitlement check path)
    Replace: 00 20 40 F6     (a MOV that effectively NOPs the check)

This corresponds to Sogeti's runtime patch in `kernel_patcher.c`:
    "IOAESAccelerator enable UID":
        (h("67 D0 40 F6"), h("00 20 40 F6"))

After patching, userspace processes (signed with `com.apple.keystore.device`
and `task_for_pid-allow` entitlements via `ldid`) can call IOAESAccelerator's
UID-key functions, which is what `bruteforce` needs.

Workflow:
    kc-patch.py <encrypted-img3-in> <iv-hex> <key-hex> <encrypted-img3-out>

Requires `xpwntool` from Legacy-iOS-Kit (https://github.com/LukeZGD/Legacy-iOS-Kit)
in PATH or in the conventional location:
    ~/Legacy-iOS-Kit/bin/{macos,linux}/<arch>/xpwntool

Tested against iOS 5.1.1 / iPod3,1 (build 9B206, kernelcache.release.n18).
The byte pattern is the same across iPhone 3GS, iPod touch 3, and iPad 1
since they share the S5L8922/8920 IOAESAccelerator implementation. The
*offset* will differ between iOS versions and (sometimes) device models, so
this tool searches the kernel binary rather than hard-coding a position.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PATCH_FROM = bytes.fromhex("67D040F6")
PATCH_TO   = bytes.fromhex("002040F6")


def find_xpwntool() -> str:
    if shutil.which("xpwntool"):
        return "xpwntool"
    home = Path.home()
    candidates = [
        home / "Legacy-iOS-Kit/bin/macos/arm64/xpwntool",
        home / "Legacy-iOS-Kit/bin/macos/x86_64/xpwntool",
        home / "Legacy-iOS-Kit/bin/linux/x86_64/xpwntool",
        home / "Legacy-iOS-Kit/bin/linux/arm64/xpwntool",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    raise SystemExit(
        "xpwntool not found. Install Legacy-iOS-Kit "
        "(https://github.com/LukeZGD/Legacy-iOS-Kit) or put xpwntool in PATH."
    )


def decrypt(xpwntool: str, in_img3: str, iv: str, key: str, out_macho: str) -> None:
    # No -decrypt flag: counterintuitively, that strips back to img3-wrapped.
    # Plain invocation gives the raw Mach-O.
    subprocess.run(
        [xpwntool, in_img3, out_macho, "-k", key, "-iv", iv],
        check=True, capture_output=True,
    )


def encrypt(xpwntool: str, in_macho: str, template_img3: str, iv: str, key: str,
            out_img3: str) -> None:
    subprocess.run(
        [xpwntool, in_macho, out_img3, "-t", template_img3, "-k", key, "-iv", iv],
        check=True, capture_output=True,
    )


def apply_patch(macho_path: str) -> int:
    data = bytearray(open(macho_path, "rb").read())
    # Confirm Mach-O 32-bit
    if data[:4] != b"\xce\xfa\xed\xfe":
        raise SystemExit(
            f"{macho_path} doesn't look like a 32-bit Mach-O "
            f"(magic {data[:4].hex()})"
        )

    occurrences = []
    i = 0
    while True:
        idx = data.find(PATCH_FROM, i)
        if idx < 0:
            break
        occurrences.append(idx)
        i = idx + 1

    if not occurrences:
        raise SystemExit(
            f"pattern {PATCH_FROM.hex()} not found in kernel: wrong device "
            f"or iOS version, or kernel already patched"
        )
    if len(occurrences) > 1:
        raise SystemExit(
            f"pattern {PATCH_FROM.hex()} found {len(occurrences)} times, "
            f"refusing to patch ambiguously. Inspect manually:\n"
            + "\n".join(f"  0x{o:x}" for o in occurrences)
        )

    off = occurrences[0]
    print(f"patching offset 0x{off:x}: "
          f"{bytes(data[off:off+4]).hex()} -> {(PATCH_TO + data[off+4:off+4][:0]).hex()}")
    data[off:off + len(PATCH_TO)] = PATCH_TO
    open(macho_path, "wb").write(bytes(data))
    return off


def main() -> None:
    if len(sys.argv) != 5:
        print(f"usage: {sys.argv[0]} <encrypted.img3> <iv-hex> <key-hex> "
              f"<patched.img3>", file=sys.stderr)
        sys.exit(1)

    in_img3, iv, key, out_img3 = sys.argv[1:]
    xpwntool = find_xpwntool()

    with tempfile.TemporaryDirectory() as tmp:
        macho = os.path.join(tmp, "kernel.macho")
        print("decrypting kernelcache...")
        decrypt(xpwntool, in_img3, iv, key, macho)

        print("applying IOAESAccelerator UID patch...")
        apply_patch(macho)

        print("re-encrypting (using original img3 as template)...")
        encrypt(xpwntool, macho, in_img3, iv, key, out_img3)

    print(f"patched img3 written to {out_img3}")


if __name__ == "__main__":
    main()
