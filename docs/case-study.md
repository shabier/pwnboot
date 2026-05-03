# Case study: forgotten-PIN iPod touch 3 data recovery

A walkthrough of one recovery start to finish. The data is redacted, the technique is the point.

## Starting state

- 32GB iPod touch 3 (model A1318, identifier `iPod3,1`, SoC S5L8922)
- iOS 4.2.1 (`SRTG:[iBoot-359.5]` revealed by limera1n's pre-exploit fingerprint)
- Forgotten 4-digit PIN, lock screen showing "iPod is disabled, connect to iTunes"
- Already past the 10 failed-attempts threshold, so iOS won't accept any more PIN attempts at the lock screen until reset. "Erase Data after 10 attempts" was not enabled (confirmed by the device still being functional, just locked)
- No iCloud or iTunes backup
- Was jailbroken at some point (Cydia, apt, dpkg, hide.dylib, libsubstrate present in the system partition)

## Phase 1: reconnaissance (the MC086 trap)

Before exploitation, confirm the hardware. Apple sold a 32GB / 64GB iPod touch "3rd gen" (A1318, iPod3,1, S5L8922) and an 8GB "3rd gen" budget version (MC086, A1288, **iPod2,1**, S5L8720) which is actually a 2nd gen wearing a 3rd-gen marketing tag. The SoCs use different bootrom exploits. limera1n applies to S5L8920/8922/8930 only.

| Marketing | Real model | Identifier | SoC | Storage |
|---|---|---|---|---|
| "iPod touch 3rd gen" (real) | A1318 | iPod3,1 | S5L8922 | 32 / 64 GB |
| "iPod touch 3rd gen 8 GB" (MC086LL/A) | A1288 | iPod2,1 | S5L8720 | 8 GB |

Verified the device is the real iPod3,1 (32GB → A1318 → S5L8922 → limera1n).

Chip-off was considered and rejected. S5L8922 has a per-device UID key fused into the SoC. The data partition is encrypted with class keys derived from `PBKDF2(PIN, UID-tangled-salt)`. The UID never leaves the chip. Reading NAND gives ciphertext you can't decrypt without the same SoC participating. Forensics labs charging $1.5k-5k will tell you the same. Skip it.

Threat model: PIN guessing must happen via a custom ramdisk so it doesn't trip iOS's lock-screen "Erase Data" counter (which it can't anymore, but cheap to do right).

## Phase 2: modern macOS Python is broken

Tried to run `alfiecg24/limera1n-pwner` directly on a recent M-series Mac. Homebrew Python 3.12/3.13 instantly fails:

```
ImportError: dlopen(.../pyexpat.cpython-313-darwin.so):
Symbol not found: _XML_SetAllocTrackerActivationThreshold
```

Homebrew's bottled Python's `pyexpat` is built against a newer libexpat than what ships in `/usr/lib/libexpat.1.dylib` on macOS 26. Every `pip` invocation crashes (pip imports `xmlrpc.client` which imports `xml.parsers.expat`).

Resolution: use Apple's bundled `/usr/bin/python3` (3.9.6). Older, but built against the same libexpat the OS ships, so no version skew. `/usr/bin/python3 -m pip install --user pyusb` works cleanly.

## Phase 3: headless Linux VM (abandoned)

First instinct was to put everything in a Linux VM via UTM, then later QEMU directly with HVF acceleration on Apple Silicon. Built it out: cloud-init seed, Ubuntu 22.04 ARM64 cloud image, headless boot, full toolchain (ipwndfu, Sogeti, Legacy-iOS-Kit) installed automatically.

Then learned: QEMU 11.x's `usb-host` device on macOS Tahoe (26.x) is broken. `device_add usb-host,vendorid=...,productid=...` crashes the QEMU process for any vendor/product, real or fake. With `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` it's possible to attach a USB device at VM boot time, but the moment the iPod re-enumerates (DFU to Recovery transition after iBSS executes), QEMU loses track and crashes.

Pivot: do everything Mac-native instead.

## Phase 4: limera1n on the Mac (works first try, ~1 second)

With Apple's Python 3.9 plus pyusb, `alfiecg24/limera1n-pwner` works after a small patch to `dfu.py` to point at Homebrew's libusb. The bundled `libusbfinder` only knows Homebrew bottle layouts up to Monterey:

```python
backend = usb.backend.libusb1.get_backend(
    find_library=lambda x: '/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib')
```

Verified end-to-end with the iPod in normal/disabled mode (returns "No Apple device in DFU Mode 0x1227 detected", clean error path), then with the iPod in DFU after holding Power+Home for 10s, releasing Power, holding Home for 10-15s.

```
Found: CPID:8922 CPRV:02 CPFM:03 SCEP:01 BDID:02 ECID:<redacted> SRTG:[iBoot-359.5]
Starting timer...
Device is now in pwned DFU Mode.
Pwned in 1.16s
```

Pwned DFU achieved on attempt 1.

## Phase 5: Mac-native Legacy-iOS-Kit fails at iBEC

Cloned Legacy-iOS-Kit on the Mac. Ran:

```sh
bash restore.sh --sshrd --device=iPod3,1 --no-color
```

It detected the existing pwned DFU, sent iBSS (100%), sent iBEC (100%), then:

```
[Log] Finding device in Recovery mode...
[Error] Failed to find device in Recovery mode (Timed out).
```

The iPod vanished from `ioreg -p IOUSB`. Not as DFU, not as Recovery. Black screen, unresponsive. Required a force-power-off (hold Power 10s) and full re-pwn cycle.

Tried with `--no-finder`, with extended Recovery-detection timeouts, with a USB hub between dongle and cable. No combination worked.

Searching the Legacy-iOS-Kit issue tracker found exactly this symptom in [#970](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/970), [#36](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/36), [#1008](https://github.com/LukeZGD/Legacy-iOS-Kit/issues/1008). Diagnosis from those threads:

> Third-party 30-pin cable plus Apple USB-C-to-USB-A dongle plus Apple Silicon Mac. The bootrom USB stack is forgiving and works through marginal cables. iBEC's USB stack is much pickier; the post-iBEC-load re-enumeration to Recovery silently drops on this combination. No software flag fixes this.

LukeZGD's standing advice: get a powered USB-A hub, or a genuine Apple cable, or move to a Linux machine. I had a Linux box to hand (Arch desktop, Ryzen 5 7600), so that was the plan.

## Phase 6: limera1n fails on AMD

Moved iPod to the Arch box. `lsusb` confirmed the device. Cloned Legacy-iOS-Kit on Arch. Ran `--sshrd`. It got to its own pwn step (`primepwn`) and looped forever:

```
*** primepwn by LukeZGD ***
Acquiring device handle.
Sending fake data.
Executing exploit.
Performing USB port reset.
... repeats ...
ERROR: Unable to connect to device

* Unfortunately, pwning may have low success rates on AMD desktop CPUs if you have one.
```

Tried `alfiecg24/limera1n-pwner` directly on Arch (different exploit implementation): 30 attempts, zero successes.

Worse: failed pwn attempts of either implementation knocked the iPod out of DFU repeatedly. Each retry meant a new DFU button dance.

The Legacy-iOS-Kit warning is real, not aspirational. limera1n's heap-overflow race depends on USB controller timing characteristics that AMD desktop chipsets get wrong consistently.

## Phase 7: split-machine pipeline (the breakthrough)

Combined the strengths:

- Mac for limera1n. Reliable in 1 to 4 attempts thanks to its USB controller timing.
- Arch for iBEC plus ramdisk. Linux's USB stack handles re-enumerations cleanly, the dongle/cable instability disappears on a USB-A port.

The insight that made it work: pwned DFU is a CPU/RAM state on the iPod, not a USB-link state. As long as the iPod stays battery-powered (don't hold Power button), it survives an arbitrary USB disconnect. The jailbreak community routinely disconnects pwned DFU for 30+ seconds during workflows. A few-second cable swap is well within margin.

The dance:

1. iPod cable USB-A end into Mac dongle. Force-power-off iPod (hold Power 10s). DFU button sequence. Verify DFU on Mac.
2. Run `limera1n-pwner` on Mac. About 1 second. Verify `PWND:[limera1n]` appears in the IOKit serial-number string.
3. Without disconnecting the 30-pin from the iPod or pressing any iPod button, swap the cable's USB-A end from the Mac dongle into a USB-A port on Arch. About 3 seconds.
4. On Arch: `cat /sys/bus/usb/devices/*/serial | grep PWND`. Confirms pwned state survived.
5. `bash restore.sh --sshrd --device=iPod3,1` on Arch. Auto-detects pwned DFU, sends iBSS, iBEC, ramdisk, kernel. Linux tracks every re-enumeration.

Result on Arch:

```
[Log] Device seems to be already in pwned DFU mode
* Pwned: limera1n
[Log] Sending iBSS... 100%
[Log] Sending iBEC... 100%
[Log] Finding device in Recovery mode...
[Log] Found device in Recovery mode.
[Log] Sending ramdisk...
[Log] Sending DeviceTree...
[Log] Sending KernelCache...
[Log] Booting, please wait...
[Log] Running iproxy for SSH...
```

SSH ramdisk booted. Device USB descriptor switched to `05ac:1299` (iPod touch 3 normal-mode product ID; the SSH ramdisk reuses it).

## Phase 8: SSH into the ramdisk plus first data wave

Modern OpenSSH refuses ssh-rsa / ssh-dss host keys by default. The ramdisk's sshd is old enough to need them re-enabled:

```sh
sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1
```

Port 6414 is what `iproxy` chose for tunneling local TCP to the iPod's SSH port.

Inside the ramdisk: minimal busybox-shaped environment. Just `bash, cat, chmod, chown, cp, dd, ls, mkdir, mv, rm, sh, tar, mount.sh, mount, mount_hfs, sshd`. No `head, tail, wc, od, du, find`, no compiler.

Mounted the data partition with `/bin/mount.sh pv`:

```
/dev/disk0s1s1 on /mnt1 (hfs, local, journaled, noatime)
/dev/disk0s1s2 on /mnt1/private/var (hfs, local, journaled, noatime, protect)
```

`protect` flag means the kernel applies per-file content protection on read. Files in the `NSFileProtectionNone` class (the iOS 4-era default for most user data) decrypt transparently using the device UID key. Files in `NSFileProtectionComplete` and similar return `Operation not permitted` because the AKS keybag isn't unlocked.

Sample read:

```sh
scp .../IMG_0001.JPG ./test.jpg
```
```
test.jpg: JPEG image data, Exif standard, 333x333, components 3
```

Real EXIF-tagged JPEG. Scope of immediate accessibility:

| Folder | Size | What |
|---|---|---|
| `Media/DCIM` | 299 MB | All photos and videos (~2,300 files) |
| `Library/AddressBook` | 1.6 MB | Contacts (sqlite) |
| `Library/SMS` | 1.6 MB | Messages (sqlite) |
| `Library/Notes` | 388 KB | Notes |
| `Library/Calendar` | 588 KB | Calendars |
| `Library/Safari` | 140 KB | Bookmarks/history |
| `Library/Mail` | 248 KB | Most files (Protected Index PIN-encrypted) |
| `Media/Recordings` | 524 KB | Voice memos |

scp'd those out individually, then a full `tar c` of `/mnt1/private/var/{mobile,root}` (~24 GB, ~3 hours streaming through iproxy at ~3 MB/s; `tar-errors.log` captured 180 PIN-encrypted files that couldn't be read).

That was the easy half. Next: brute-force the PIN to access the other 180.

## Phase 9: cross-compiling on modern macOS

To run Sogeti's `bruteforce.c` on the iPod, I needed an armv7 Mach-O binary that loads on iOS 5.1.1. The conventional path is "install Xcode 4.2 with the iOS 4.2 SDK." Xcode 4.x doesn't run on Apple Silicon, and `developer.apple.com/download/all/` only goes back so far cleanly with current Apple ID requirements.

Alternative: build with modern Xcode/clang plus a current iPhoneOS SDK, then post-process the binary to look like an iOS 5-era Mach-O.

The chain that worked:

1. Source-level fix: modern SDK marks `kIOMasterPortDefault` as "unavailable on iOS." The symbol resolves to `0` at runtime; `sed -i 's/kIOMasterPortDefault/0/g'` across Sogeti's `*.c *.h` removes the deprecation gate without changing behavior.

2. Re-enable the patcher: Sogeti shipped `patch_IOAESAccelerator()` commented out in `IOAESAccelerator.c`, despite the print statement above it making it look active. Uncomment.

3. Compile flags:

   ```
   clang -arch armv7 -isysroot $IPHONEOS_SDK -miphoneos-version-min=6.0 \
         -Wl,-no_pie -Wl,-e,_start ...
   ```

   `=6.0` is the lowest the modern linker accepts (warns and silently bumps below that). `-no_pie` because LC_UNIXTHREAD assumes a fixed entry vmaddr. `-e,_start` so the entry point is the custom stub.

4. Custom `_start`: modern toolchain doesn't link `crt1.o`. With LC_UNIXTHREAD you jump straight to entry without setup, so `main()` reads garbage argc/argv and segfaults. Wrote an armv7 stub that reads argc from `[sp]`, computes argv/envp, calls `_main`, then `_exit`. `tools/start.S`.

5. Mach-O surgery: modern `ld` always emits `LC_MAIN` (added Xcode 4.5 / iOS 6 SDK). iOS 5.1.1 dyld doesn't understand it. Binary loads, dyld resolves all symbols, and segfaults before reaching `_start`. Wrote `tools/lc_main_to_unixthread.py`. Parses Mach-O 32-bit, finds `LC_MAIN`, computes entry vmaddr from `entryoff + __TEXT.vmaddr - __TEXT.fileoff`, splices in an 84-byte `LC_UNIXTHREAD` (ARM_THREAD_STATE, 17 regs, PC at index 15), updates `sizeofcmds`, zero-pads to keep file size constant.

6. Sign with `ldid`. Ad-hoc signature with Sogeti's entitlements (`com.apple.keystore.device`, `task_for_pid-allow`, `run-unsigned-code`, `get-task-allow`).

The whole chain is `build-bruteforce.sh` in this repo.

## Phase 10: first run, the silent kernel-patch failure

Pushed the binary to the ramdisk, ran it. Output:

```
Trying to patch IOAESAccelerator kernel extension to allow UID key usage
task_for_pid returned 5 : missing tfp0 kernel patch or wrong entitlements
IOAESAccelerator returned: e00002c1
```

`e00002c1` = `kIOReturnNotPrivileged`. The runtime kernel patcher uses `task_for_pid(0)` plus `vm_write` to modify kernel memory in place. iOS 5.1.1's ramdisk kernel doesn't grant TFP0 to userspace processes even with the entitlement. TFP0 itself is gated behind a kernel patch I didn't have.

Sogeti's design assumed a pre-patched kernel. The runtime patcher was meant to apply additional patches on top. Starting from a stock kernelcache, it stalls.

## Phase 11: patching the kernelcache offline

Solution: apply the patch before the kernel boots, by editing the kernelcache file itself.

Sogeti's `kernel_patcher.c` writes:

```
"IOAESAccelerator enable UID":
    (h("67 D0 40 F6"), h("00 20 40 F6"))
```

Two bytes change. Just need to do it in the kernelcache binary instead of in kernel memory.

Steps:

1. Get the encrypted kernelcache. Either pull from the device's `/mnt1/System/Library/Caches/com.apple.kernelcaches/kernelcache`, or `pzb` it from the appropriate IPSW. Legacy-iOS-Kit caches both during its `--sshrd` flow.

2. Get the firmware key. Legacy-iOS-Kit's per-device `saved/firmware/<device>/<build>/index.html` cache mirrors the public theiphonewiki firmware-key tables. For this build the entry was:

   ```json
   {"image":"Kernelcache",
    "iv":"<32 hex>",
    "key":"<64 hex>"}
   ```

3. Decrypt to plain Mach-O:

   ```sh
   xpwntool encrypted.img3 plain.macho -k <key> -iv <iv>
   ```

   Counterintuitively, omit the `-decrypt` flag. With `-decrypt` you get back an img3 with decrypted-but-still-LZSS-compressed data inside. Without the flag, xpwntool decrypts AND decompresses, giving plain Mach-O.

   Verify: `otool -hv plain.macho` shows `MH_MAGIC ARM`.

4. Find and patch the byte pattern:

   ```python
   data = bytearray(open("plain.macho", "rb").read())
   pattern = bytes.fromhex("67D040F6")
   idx = data.find(pattern)  # one occurrence in this kernel
   data[idx] = 0x00
   data[idx + 1] = 0x20
   open("plain.macho", "wb").write(bytes(data))
   ```

5. Re-pack as encrypted img3 using the original encrypted file as a template:

   ```sh
   xpwntool plain.macho patched.img3 -t encrypted.img3 -k <key> -iv <iv>
   ```

6. Drop into Legacy-iOS-Kit's cache:

   ```sh
   cp patched.img3 ~/Legacy-iOS-Kit/saved/<device>/ramdisk_<build>/kernelcache.release.<codename>
   ```

`tools/kc-patch.py` automates 3 through 5.

## Phase 12: second boot, second brute-force

Power-cycle, re-DFU, re-pwn, swap to Arch, run `--sshrd` again. Legacy-iOS-Kit's flow picks up the patched kernel from the cache directory, sends it during the boot sequence. Apple logo plus spinning wheel briefly (lost the verbose-boot flag somewhere, cosmetic), then SSH ramdisk up.

Same `bruteforce` binary, this time without the runtime patcher hitting TFP0:

```
Writing results to <uuid>.plist
```

...and then five minutes of silence. Then exit code 0. No "Found passcode" line.

The plist was written. Inspecting it: `DKey`, `EMF`, real entropy. Kernel patch confirmed working: `IOAES_key835()` returned the real UID-derived key 0x835. Sogeti's binary got past the IOAES setup. But it couldn't unlock the keybag with any of 0000-9999.

Suspicion: not a brute-force failure, but the wrong brute-force method. Sogeti's binary has two:

| Mode | Flag | Path |
|---|---|---|
| `bruteforceWithAppleKeyStore` | (default) | Calls `AppleKeyStoreUnlockDevice` IOKit user client per attempt |
| `bruteforceUserland` | `-u` | Computes everything in userspace using the parsed keybag plus `key835` |

The default mode runs through 10000 PINs and never matches because of an AKS state-machine quirk on this ramdisk environment.

Re-ran with `-u`:

```
0000
0001
0002
...
NNNN
Found passcode : NNNN
Keybag version : 3
Keybag keys : 10
... (all 10 class keys printed) ...
Passcode key : <32 bytes hex>
Key 0x835    : <16 bytes hex>
```

PIN found in ~30 seconds. All 10 class keys derived. Plist on the iPod overwritten with the unlocked-keybag version (now ~9 KB, was ~8 KB). Saved to `keybag-with-passcode.plist`.

That plist is the master artifact. Combined with a raw dump of the data partition and Sogeti's `emf_decrypter.py`, every previously-PIN-protected file decrypts.

## Phase 13: raw partition dump for offline decryption

Goal: recover the 180 PIN-protected files. Mounted reads through `/mnt2` still fail (kernel applies `MNT_PROTECT` automatically; AKS keybag isn't accepting the PIN through the user-client path even though I had the keys).

Resolution: dump the raw block device. `emf_decrypter.py` walks the HFS+ catalog inside an image and decrypts files using the class keys.

Surprises along the way:

| Try | Result |
|---|---|
| `dd if=/dev/disk0s1s2 bs=1m` | `dd: invalid number '1m'`. iOS dd wants uppercase or numeric |
| `dd if=/dev/disk0s1s2 bs=1048576` | `Resource busy`. `/mnt2` still mounted from it; ramdisk has no `umount` |
| Wrote a tiny C `unmount(2)` wrapper (`tools/umount.c`) | works, partition free |
| `dd if=/dev/disk0s1s2 bs=4096` and `bs=16M` | `Invalid argument`. Tried other power-of-two sizes too, all EINVAL |
| Wrote a C `read()`-based reader to confirm dd wasn't the issue | same `errno=22 (EINVAL)`. Kernel-side, not dd |
| `dd if=/dev/rdisk0s1s2 bs=8192` (the exact recipe in Sogeti's `dump_data_partition.sh`) | works, ~3 MB/s sustained |

Two specific things matter: `/dev/rdisk*` (character device, different code path than `/dev/disk*`) and `bs=8192`. Sogeti had this written down 14 years ago, just had to find it.

Streamed the 30 GB partition through iproxy plus SSH (`-c aes128-ctr -o Compression=no` to minimize SSH overhead, encrypted bytes don't compress) to the Arch box. About 3 hours.

Final piece: `emf_decrypter.py` from `iphone-dataprotection/python_scripts/`, run with the captured `.img` and the keybag plist. Produces a fully-decrypted directory tree mirroring the iPod's `/private/var`.

## Outcome

- ~302 MB of immediately-readable user data captured during phase 8
- 24 GB tarball of the rest of `/private/var` from phase 8
- 30 GB raw data-partition image from phase 13, decryptable offline with the saved keybag plist plus `emf_decrypter.py`
- iPod's flash never modified. The device is in exactly the state it started in (locked, still PIN-protected at the lock screen). A power-cycle returns it to its pre-recovery state, no traces of the SSH ramdisk

End-to-end session time: ~7 to 8 hours, most of it spent navigating dead ends (USB / cable / AMD / QEMU / macOS Python). The actual cryptographic work (pwn DFU, patch kernelcache, run bruteforce) totals maybe 20 minutes of compute and a few dozen lines of new code.

## What I'd do differently

- **Have a genuine Apple 30-pin cable to hand.** Half the dead ends came from a third-party cable plus USB-C-to-USB-A dongle on an Apple Silicon Mac. The split-machine workaround is fine, but a real Apple cable would have made the whole pipeline fit on one machine.
- **Skip the VM detour.** I spent meaningful time setting up a headless QEMU + cloud-init pipeline before learning that QEMU's `usb-host` is broken on macOS Tahoe. If I were starting over: try Mac-native first, then go straight to bare-metal Linux if USB chokes. Don't put a hypervisor between the host and the iPod.
- **Read Sogeti's source more carefully up front.** Two things I found late would have saved hours: `patch_IOAESAccelerator()` is commented out by default, and the second brute-force method (`-u`) exists and is the one that works on iOS 5 ramdisks. Both are right there in the source, both bit me at runtime.
- **Read `dump_data_partition.sh` before reinventing it.** The `bs=8192` on `/dev/rdisk*` recipe is literally one line of an existing Sogeti script. I burned an hour discovering EINVAL through experimentation before going back and finding that line.
