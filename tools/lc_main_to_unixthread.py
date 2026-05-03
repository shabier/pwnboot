#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 shabier and the pwnboot contributors.
"""
Convert LC_MAIN load command to LC_UNIXTHREAD in a 32-bit Mach-O binary so it
can run on pre-iOS-6 dyld.

Modern Apple `ld` always emits LC_MAIN (added in Xcode 4.5 / iOS 6 SDK / OS X
10.8) and refuses iPhoneOS deployment targets older than 6.0. iOS 5.x and
earlier dyld doesn't understand LC_MAIN, so binaries built with the modern
toolchain silently segfault before ever reaching `main()`.

This tool surgically rewrites the load command in-place:

  - Locates the LC_MAIN command (cmd=0x80000028)
  - Computes the entry point's virtual address from
    `entryoff + __TEXT.vmaddr - __TEXT.fileoff`
  - Builds an 84-byte LC_UNIXTHREAD command (ARM_THREAD_STATE, 17 registers,
    PC at index 15)
  - Splices it into the load-commands area, shifts the trailing commands,
    zero-pads to keep the file size constant
  - Updates `sizeofcmds` in the Mach-O header

The binary still must NOT be PIE (LC_UNIXTHREAD assumes a fixed entry vmaddr).
Build with `-Wl,-no_pie`.

You also need a `_start` stub that sets up argc/argv from the initial stack
(LC_MAIN binaries don't link `crt1.o`; dyld does that work and calls main
directly. With LC_UNIXTHREAD you jump straight to entry, so you have to do
the argv setup yourself). See `tools/start.S` in this repo for a minimal
armv7 _start.

Sample usage:
    clang -arch armv7 -isysroot iPhoneOS.sdk -miphoneos-version-min=6.0 \\
          -Wl,-no_pie -Wl,-e,_start -o out.bin start.S main.c
    python3 lc_main_to_unixthread.py out.bin out-fixed.bin
    ldid -S out-fixed.bin   # ad-hoc sign so iOS will load it

Tested against:
    - iOS 5.1.1 ramdisk dyld on S5L8922 (iPod3,1 / iPhone 3GS / iPad 1)
    - Built with Xcode 26.x SDK + clang on macOS Tahoe (26.2)

Limitations:
    - 32-bit Mach-O only (MH_MAGIC = 0xfeedface).
    - Single-architecture binary (no fat slices).
    - Replaces LC_MAIN once; assumes only one such command.
"""
import struct
import sys

LC_SEGMENT     = 0x1
LC_UNIXTHREAD  = 0x5
LC_MAIN        = 0x80000028  # MH_NOLOAD-or-fail flag set on this command id
ARM_THREAD_STATE = 1
ARM_THREAD_STATE_COUNT = 17  # r0..r12, sp, lr, pc, cpsr


def patch(infile: str, outfile: str) -> None:
    data = bytearray(open(infile, "rb").read())
    magic = struct.unpack("<I", data[0:4])[0]
    if magic != 0xFEEDFACE:
        raise SystemExit(f"not a 32-bit Mach-O (magic 0x{magic:x})")

    ncmds      = struct.unpack("<I", data[16:20])[0]
    sizeofcmds = struct.unpack("<I", data[20:24])[0]

    # Single pass: find LC_MAIN, find __TEXT segment, find lowest section
    # offset (the real upper bound for load-commands area).
    offset = 28
    lc_main_off = lc_main_size = entryoff = None
    text_vmaddr = text_fileoff = None
    first_section_offset = None

    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack("<II", data[offset:offset + 8])

        if cmd == LC_MAIN:
            lc_main_off = offset
            lc_main_size = cmdsize
            entryoff = struct.unpack("<Q", data[offset + 8:offset + 16])[0]

        elif cmd == LC_SEGMENT:
            segname = data[offset + 8:offset + 24].rstrip(b"\x00").decode()
            vmaddr  = struct.unpack("<I", data[offset + 24:offset + 28])[0]
            fileoff = struct.unpack("<I", data[offset + 32:offset + 36])[0]
            nsects  = struct.unpack("<I", data[offset + 48:offset + 52])[0]

            if segname == "__TEXT":
                text_vmaddr, text_fileoff = vmaddr, fileoff

            # Walk this segment's sections to find the lowest non-zero file
            # offset. That bounds where we can grow the load-commands area.
            sect_off = offset + 56  # 32-bit segment_command is 56 bytes
            for _s in range(nsects):
                sect_size   = struct.unpack("<I", data[sect_off + 36:sect_off + 40])[0]
                sect_offset = struct.unpack("<I", data[sect_off + 40:sect_off + 44])[0]
                if sect_size > 0 and sect_offset > 0:
                    if first_section_offset is None or sect_offset < first_section_offset:
                        first_section_offset = sect_offset
                sect_off += 68  # 32-bit section is 68 bytes

        offset += cmdsize

    if lc_main_off is None:
        raise SystemExit("no LC_MAIN found. already converted?")
    if text_vmaddr is None:
        raise SystemExit("no __TEXT segment")
    if first_section_offset is None:
        raise SystemExit("no sections with file content")

    entry_vaddr = text_vmaddr + (entryoff - text_fileoff)
    new_sizeofcmds = sizeofcmds + (84 - lc_main_size)

    if 28 + new_sizeofcmds > first_section_offset:
        raise SystemExit(
            f"new load-cmds area ({new_sizeofcmds}) would overflow into first "
            f"section at 0x{first_section_offset:x}"
        )

    # Build LC_UNIXTHREAD: cmd + cmdsize=84 + flavor + count + 17 regs (PC at 15)
    regs = [0] * ARM_THREAD_STATE_COUNT
    regs[15] = entry_vaddr
    new_lc = (
        struct.pack("<II", LC_UNIXTHREAD, 84)
        + struct.pack("<II", ARM_THREAD_STATE, ARM_THREAD_STATE_COUNT)
        + struct.pack(f"<{ARM_THREAD_STATE_COUNT}I", *regs)
    )
    assert len(new_lc) == 84

    # Splice.
    # 1. Update sizeofcmds in header.
    # 2. Save tail (everything after LC_MAIN within the original load-cmds area).
    # 3. Replace the LC_MAIN bytes with new_lc, keeping file size constant.
    # 4. Re-place the tail right after the new LC_UNIXTHREAD.
    # 5. Zero-fill the gap between the new last command and the first section.
    out = bytearray(data)
    out[20:24] = struct.pack("<I", new_sizeofcmds)

    tail_start = lc_main_off + lc_main_size
    tail_end = 28 + sizeofcmds
    tail = bytes(out[tail_start:tail_end])

    out[lc_main_off:lc_main_off + 84] = new_lc
    out[lc_main_off + 84:lc_main_off + 84 + len(tail)] = tail

    # Zero out anything between the (new) load commands and the first section.
    new_end = lc_main_off + 84 + len(tail)
    for i in range(new_end, first_section_offset):
        out[i] = 0

    if len(out) != len(data):
        raise SystemExit(f"file size changed unexpectedly: {len(data)} -> {len(out)}")

    with open(outfile, "wb") as f:
        f.write(bytes(out))

    print(f"LC_MAIN at 0x{lc_main_off:x} (entryoff 0x{entryoff:x}) "
          f"-> LC_UNIXTHREAD with PC=0x{entry_vaddr:x}")
    print(f"sizeofcmds 0x{sizeofcmds:x} -> 0x{new_sizeofcmds:x}")
    print(f"wrote {outfile} ({len(out)} bytes, unchanged)")


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input.macho> <output.macho>", file=sys.stderr)
        sys.exit(1)
    patch(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
