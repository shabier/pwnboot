# Caveats

The dead ends I went through, ranked by how much time they cost. Save yourself the trouble.

## 1. Modern `ld` refuses iOS deployment targets older than 6.0

```
ld: building for iOS with 4.0 minimum deployment target is no longer supported
```

`-miphoneos-version-min=5.0` triggers a warning that silently bumps to 7.0. `=6.0` is the lowest the modern linker actually accepts.

Workaround: build with `=6.0`, accept that the linker will emit `LC_MAIN`, then post-process the binary with `tools/lc_main_to_unixthread.py` to convert it to `LC_UNIXTHREAD` for iOS 5 dyld.

## 2. `LC_MAIN` segfaults on iOS 5 and earlier

`LC_MAIN` was added in Xcode 4.5 / iOS 6 SDK. iOS 5.1.1 dyld doesn't understand it. The binary loads (dyld resolves all symbols) but segfaults before reaching `main`.

Workaround: `lc_main_to_unixthread.py`. Replaces `LC_MAIN` with an `LC_UNIXTHREAD` whose PC register points at the same entry virtual address.

## 3. `LC_UNIXTHREAD` binaries don't have `crt1.o` linked

Modern toolchains stopped linking the C runtime startup file because LC_MAIN binaries delegate argv/envp setup to dyld. With LC_UNIXTHREAD you jump straight to entry, no setup, so `main()` reads garbage and segfaults.

Workaround: `tools/start.S`. Twelve lines of armv7 assembly that read argc from `[sp]`, compute argv/envp, call `_main`, then `_exit`.

Build with `-Wl,-e,_start` so the entry point is our stub, not `_main`. The converter then writes that stub address into the LC_UNIXTHREAD PC register.

## 4. `kIOMasterPortDefault` is "unavailable on iOS" in modern SDKs

```
error: 'kIOMasterPortDefault' is unavailable: not available on iOS
note: 'kIOMasterPortDefault' has been explicitly marked unavailable here
```

The actual symbol resolves to `0` at runtime on every iOS version that has it. The SDK's deprecation gate is purely a header-level warning.

Workaround: sed the source. Replace `kIOMasterPortDefault` with literal `0` everywhere it appears. Don't try `#define kIOMasterPortDefault 0`, that conflicts with the const declaration in `IOKitLib.h`.

`build-bruteforce.sh` does this automatically.

## 5. Sogeti's `patch_IOAESAccelerator()` call is commented out

In `iphone-dataprotection/ramdisk_tools/IOAESAccelerator.c`, the actual call to the runtime kernel patcher is `// patch_IOAESAccelerator();`, disabled. The "Trying to patch IOAESAccelerator kernel extension" log line above it prints unconditionally, which makes it look like the patcher is running when it isn't.

Workaround: uncomment it. `build-bruteforce.sh` does this automatically.

But also see #6. Even with the runtime patcher enabled, it fails on iOS 5.1.1 ramdisk because of TFP0.

## 6. Runtime kernel patching needs TFP0, which itself needs kernel patching

Sogeti's `kernel_patcher.c` does its work via `task_for_pid(0)` plus `vm_write`. On a clean iOS 5.1.1 kernel, `task_for_pid(mach_task_self(), 0, &kernel_task)` returns `KERN_FAILURE (5)` because TFP0 is gated behind a kernel patch we don't have.

```
task_for_pid returned 5 : missing tfp0 kernel patch or wrong entitlements
```

Workaround: apply the IOAESAccelerator patch offline to the kernelcache instead. Same byte pattern Sogeti's runtime patcher would have written, just done before iBoot loads the kernel. See `tools/kc-patch.py`.

## 7. `bruteforceWithAppleKeyStore` (the default) silently fails on iOS 5

Sogeti's binary has two brute-force paths:

| Method | Flag | Path |
|---|---|---|
| `bruteforceWithAppleKeyStore` | (default, no flag) | Calls `AppleKeyStoreUnlockDevice` IOKit user client per attempt |
| `bruteforceUserland` | `-u` | Computes everything in userspace using parsed keybag plus `key835` |

The default method runs to completion across all 10000 PINs without finding any of them. The `-u` method finds the PIN immediately. Probable cause: an AKS state-machine quirk on the patched-but-userspace-isolated iOS 5 ramdisk. The keybag set via `AppleKeyStoreKeyBagSetSystem` doesn't accept user-supplied passcodes the way the on-disk system keybag does.

Always pass `-u`. Don't waste time wondering why the default mode "works" but never finds the PIN.

## 8. iOS rejects raw `read()` of a CP-protected partition's block device

```
$ dd if=/dev/disk0s1s2 of=/dev/null bs=4096 count=2
dd: reading `/dev/disk0s1s2': Invalid argument
```

Same error from a custom C `read()` based reader (`errno=22 = EINVAL`). Not a `dd` bug. The iOS HFS+ block layer refuses raw reads of partitions with content protection enabled.

Workaround: `dd if=/dev/rdisk0s1s2 bs=8192`. Two specific things matter:

- `/dev/rdisk*` not `/dev/disk*` (character device, different code path)
- `bs=8192` (4K and 16M both EINVAL)

Buried in `iphone-dataprotection/dump_data_partition.sh`. Found this the hard way.

## 9. SSH ramdisk runs minimal busybox: no umount, no head, no tail

The Legacy-iOS-Kit SSH ramdisk has just `bash, cat, chmod, chown, cp, dd, ls, mkdir, mv, rm, sh, tar, mount, mount_hfs, sshd`. No `umount(8)`, no `head`, no `tail`, no `find`, no `wc`, no `od`, no `du`, no compiler.

Workarounds:

- `tools/umount.c` for unmounting `/mnt2` so you can `dd` the raw partition.
- For text utilities, push lines back to the host and process there.
- For monitoring tar streams, `stat -c %s` over SSH every few minutes from outside.

## 10. Modern OpenSSH refuses ssh-rsa and ssh-dss host keys by default

The Legacy-iOS-Kit SSH ramdisk uses old crypto. OpenSSH 8.8+ rejects ssh-rsa/dsa server host keys without explicit opt-in.

Workaround:

```
ssh -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa ...
```

Always include those flags when SSH-ing into the ramdisk.

## 11. USB-C-to-USB-A dongle plus third-party 30-pin cable plus Apple Silicon Mac

DFU mode works fine. iBEC's USB re-enumeration to Recovery silently drops. iPod disappears from `ioreg -p IOUSB` after iBEC is sent. No software flag fixes this.

The bootrom USB stack is forgiving, iBEC's is much pickier. The dongle plus cable combination falls apart at the iBEC re-enumeration step. Documented in Legacy-iOS-Kit issues [#970](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/970), [#36](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/36), [#1008](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/1008).

Workaround: use a Linux machine for the post-pwn / iBEC steps. Mac is fine for limera1n. Split the work. Pwned DFU survives a USB cable swap as long as the iPod stays battery-powered. See `pipeline.md`.

## 12. AMD desktop CPUs are unreliable for limera1n

Legacy-iOS-Kit's own warning: "pwning may have low success rates on AMD desktop CPUs." Tested with both `primepwn` and `alfiecg24/limera1n-pwner` on a Ryzen 5 7600: ~30 attempts, zero successes. The exploit's USB-timing race fails on AMD's USB controllers.

Workaround: do the limera1n step on Intel or Apple Silicon. AMD is fine for the post-pwn iBEC plus ramdisk plus bruteforce work where timing isn't critical.

## 13. QEMU `usb-host` on macOS Apple Silicon (Tahoe 26.x)

Crashes when `device_add usb-host` is called for any device, real or fake. Hot-plug is broken. Boot-time attach (with `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`) works but doesn't survive USB re-enumeration, which is exactly the wrong property for an iOS device that transitions through DFU then Recovery then ramdisk.

Workaround: don't use QEMU for the iOS USB side. Either do everything on the Mac (where macOS handles USB transitions natively, modulo cable issues) or move to a real Linux box for the iBEC step.

## 14. Homebrew Python on macOS 26.x has a stale libexpat link

Bottled Python 3.12 / 3.13 references symbols from a newer libexpat than what ships in `/usr/lib/libexpat.1.dylib`:

```
ImportError: ... Symbol not found: _XML_SetAllocTrackerActivationThreshold
```

`pip` is broken because it imports `xmlrpc.client` which imports `xml.parsers.expat`.

Workaround: use Apple's bundled `/usr/bin/python3` (3.9.6). Older but matches the OS's libexpat exactly. `pip install --user pyusb` works fine.

Don't try to `install_name_tool` the Homebrew Python's pyexpat to point at brew's libexpat. Invalidates the code signature, brew might overwrite, etc. Just use Apple Python.
