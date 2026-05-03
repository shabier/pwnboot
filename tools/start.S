// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 shabier and the pwnboot contributors.
//
// Minimal _start stub for armv7 iOS Mach-O binaries that use LC_UNIXTHREAD
// instead of LC_MAIN.
//
// LC_MAIN binaries delegate argv/envp setup and main() invocation to dyld.
// LC_UNIXTHREAD binaries (the older format used by pre-iOS-6 dyld) jump
// directly to the entry point with no setup, so we have to read argc from
// the initial stack ourselves, compute argv and envp pointers, then call
// main() and exit() with its return value.
//
// Modern toolchains don't link the old crt1.o startup file, so this stub
// stands in for it. Pair with `lc_main_to_unixthread.py` to make a binary
// that loads cleanly on iOS 5.1.1 dyld (or in principle anything that reads
// LC_UNIXTHREAD: older OS X kernel-mode binaries, embedded targets).
//
// Build:
//   clang -arch armv7 -isysroot iPhoneOS.sdk -miphoneos-version-min=6.0 \
//         -Wl,-no_pie -Wl,-e,_start -o out start.S main.c
//
// Stack layout on entry (Darwin/iOS):
//   [sp+0]              = argc (uint32_t)
//   [sp+4 .. sp+4+(argc+1)*4]  = argv pointers, including a NULL terminator
//   [following]         = envp pointers, NULL-terminated
//   [following]         = apple[] pointers (executable path, etc.), NULL-terminated

.global _start
.text
.align 2

_start:
    ldr r0, [sp]                @ r0 = argc
    add r1, sp, #4              @ r1 = argv (first ptr right after argc)
    add r2, r0, #1              @ r2 = argc + 1 (count incl. argv[argc] NULL)
    add r2, r1, r2, lsl #2      @ r2 = envp = argv + (argc + 1) * 4
    bl  _main                   @ call user main(argc, argv, envp); returns in r0
    bl  _exit                   @ exit(r0); should not return
loop:
    b   loop                    @ defensive, should be unreachable
