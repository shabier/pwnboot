# pwnboot

A modern toolchain for booting custom kernels on pre-A7 iOS devices (iPhone 3GS, iPod touch 3, iPad 1). Modern-clang cross-compile pipeline for iOS 5 armv7 binaries, an offline kernelcache patcher, and a forgotten-PIN data recovery walkthrough.

## The story

I had a 32GB iPod touch 3, jailbroken back in the day, sat in a drawer for the better part of a decade, with a forgotten 4-digit PIN. iOS was locked at the "iPod is disabled" screen. No backup.

The standard answer today is "you can't." Forensics labs charging four figures will tell you the same: the data is encrypted with a key derived from the PIN, and the device is too old for any current commercial unlock service.

What I ended up with: the iPod data, the device unmodified, and a small set of tools that let anyone with this device class do the same thing without an archived Xcode 4.2 install or a 2014 Mac.

[Read the full case study →](docs/case-study.md)

## Why this exists

Sogeti's [iphone-dataprotection](https://github.com/dinosec/iphone-dataprotection) was the canonical toolkit for recovering data from locked pre-A7 iOS devices, back when its assumed environment (OS X 10.8 / 10.9, Xcode 4.2, the iOS 4.2 SDK) actually existed. None of that runs on a modern Apple Silicon Mac. Every blog post and wiki page from that era starts with "install Xcode 4.2," and that's where most people stop today.

This repo is the workaround. You build a working armv7 iOS 5 compatible binary on macOS Tahoe (26.x) with current clang and a current iPhoneOS SDK, no archived Xcode required. The technique is small, the code is small, but figuring it out wasn't.

## What I built

`tools/lc_main_to_unixthread.py`. Mach-O 32-bit surgery. Modern `ld` always emits `LC_MAIN` (added Xcode 4.5 / iOS 6 SDK / OS X 10.8) and refuses `-miphoneos-version-min` below 6.0. iOS 5 dyld doesn't understand `LC_MAIN`. This tool splices `LC_UNIXTHREAD` in and computes the entry vmaddr from the existing `entryoff` and `__TEXT` segment.

`tools/start.S`. Minimal armv7 `_start` stub. `LC_UNIXTHREAD` binaries jump straight to entry, so we have to read argc from `[sp]`, set up argv/envp, and call `main()` ourselves.

`tools/umount.c`. Tiny helper because the Legacy-iOS-Kit SSH ramdisk doesn't have `umount(8)`. Useful for freeing `/dev/disk0sNsM` so you can `dd` the raw partition.

`tools/kc-patch.py`. Offline kernelcache patcher. Applies Sogeti's "IOAESAccelerator enable UID" patch (`67 D0 40 F6` becomes `00 20 40 F6`) to a decrypted kernel and re-packs as img3. Sogeti's runtime patcher needs TFP0, which itself needs kernel patches. Doing the patch offline before iBoot loads the kernel sidesteps the whole chicken-and-egg.

`build-bruteforce.sh`. End-to-end build. Clones Sogeti, applies the source patches you need on a modern compiler (`kIOMasterPortDefault` to `0`, uncomment the `patch_IOAESAccelerator()` call Sogeti shipped commented out), invokes clang, runs the LC_MAIN converter, signs with `ldid`. Output is ready to scp into a ramdisk.

## Documentation

- [`docs/case-study.md`](docs/case-study.md) — the full recovery walkthrough, phase by phase, including all the dead ends.
- [`docs/pipeline.md`](docs/pipeline.md) — howto for someone running this against their own device. Covers the DFU dance, the split-machine pipeline, and the data-partition dump.
- [`docs/caveats.md`](docs/caveats.md) — every dead end I hit, ranked by how much time it cost. Save yourself the trouble.

## Builds on

[`LukeZGD/Legacy-iOS-Kit`](https://github.com/LukeZGD/Legacy-iOS-Kit). Boots the SSH ramdisk on the iPod via pwned DFU plus iBSS/iBEC plus custom kernel. We hand it our patched kernelcache, it does the rest. Has `xpwntool` and `ldid` for both Linux and macOS.

[`alfiecg24/limera1n-pwner`](https://github.com/alfiecg24/limera1n-pwner). The limera1n bootrom exploit, ported to Python 3 and tested on Apple Silicon. See `docs/caveats.md` for a small `dfu.py` patch needed on macOS 26.

[`dinosec/iphone-dataprotection`](https://github.com/dinosec/iphone-dataprotection). The actual `bruteforce.c` source, the kernel patch addresses, and the offline `emf_decrypter.py` for decrypting raw partition images.

[theiphonewiki firmware keys](https://www.theiphonewiki.com/wiki/Firmware_Keys). `iv` and `key` for any kernelcache you want to decrypt.

## Hardware

The tooling is generic. The kernelcache byte-pattern patch is verified on:

| Device | SoC | Codename | iOS | Build |
|---|---|---|---|---|
| iPod touch 3 (32GB / 64GB) | S5L8922 | n18ap | 5.1.1 (target ramdisk) | 9B206 |

Conjecture, not yet tested: the same byte pattern should also apply to S5L8920 (iPhone 3GS) and S5L8930 (iPad 1) since they share the IOAESAccelerator implementation. Offsets will differ. The patcher searches rather than hard-coding a position, so other devices in the family should work as long as the pattern occurs exactly once.

## Quick start

```sh
# 1. Build the bruteforce binary on macOS
./build-bruteforce.sh

# 2. Patch the kernelcache (you provide the encrypted img3, iv, key)
python3 tools/kc-patch.py kernelcache.release.n18 <iv> <key> kernelcache.patched.n18

# 3. Drop the patched kernel into Legacy-iOS-Kit's cache
cp kernelcache.patched.n18 ~/Legacy-iOS-Kit/saved/iPod3,1/ramdisk_9B206/kernelcache.release.n18

# 4. Boot the SSH ramdisk (Linux side, where USB re-enumeration is reliable)
cd ~/Legacy-iOS-Kit && bash restore.sh --sshrd --device=iPod3,1

# 5. Once SSH is up via iproxy, scp in the binary and run
sshpass -p alpine scp -P 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  build/bruteforce-fixed root@127.0.0.1:/var/root/bruteforce
sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  root@127.0.0.1 '/var/root/bruteforce -u'
```

Full walkthrough (DFU sequence, split-machine setup, data-partition dump): [`docs/pipeline.md`](docs/pipeline.md).

## Scope

This is for recovering data from devices you own. The whole pipeline assumes physical access to the iPod plus a willingness to dance the DFU button sequence. Nothing here is remotely exploitable; nothing here gets past anything iOS 6+ does to harden against this same family of attacks.

## License

GPL-3.0-or-later, with a section 7(b) attribution requirement: redistributors must preserve `CREDITS.md` and the copyright notice. See `LICENSE`. Sogeti, axi0mX, alfiecg24, LukeZGD do the real work. This repo is connective tissue.
