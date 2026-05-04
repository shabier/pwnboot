# Lockout reset

How to clear the "iPod is disabled, connect to iTunes" state on a pre-A7 iOS device when you know the PIN but iOS isn't accepting it anymore. Useful after a failed brute-force, or after someone mashed the keypad past 10 attempts. Non-destructive: keeps every file on the device.

Tested on iPod touch 3 (iPod3,1) running iOS 4.2.1. Should apply to other iOS 4 / iOS 5 builds in the same device class (iPhone 3GS, iPad 1, S5L8920/8922/8930).

## Why this is a plist edit and not a crypto attack

iOS 4 and iOS 5 don't have a Secure Enclave. The hardware Secure Enclave shipped with the A7 SoC (iPhone 5s) in 2013, well after the device class this repo targets. Without an SE, the failed-attempts counter has nowhere to live in silicon, so iOS just stores it as a SpringBoard preference.

Three keys in `/var/mobile/Library/Preferences/com.apple.springboard.plist`:

| Key | Type | What it does |
|---|---|---|
| `SBDeviceLockFailedAttempts` | int | Counts wrong PIN tries. Past 6, the lock screen shows escalating delays. Past 10, it shows "iPod is disabled" and stops accepting input |
| `SBDeviceLockBlocked` | bool | Set true when the lockout fires. Lock screen reads this to decide whether to render the PIN keypad at all |
| `SBDeviceLockBlockTimeIntervalSinceReferenceDate` | real | Timestamp of when the lockout started. Used by the disabled-screen UI |

The plist is `NSFileProtectionNone` (class 4). It has to be readable at boot, before any passcode is entered, so iOS doesn't encrypt it with a class key that depends on the PIN. That means no class keys needed, just a writable mount.

Apple's keybag, the AKS user client, and the kernel-side passcode validation never look at this counter. With the right PIN, the keybag still unlocks. The only thing keeping you out is SpringBoard's UI gate.

## What you need

Same setup as the rest of this repo:

- A device of the limera1n class (S5L8920/8922/8930)
- Mac for the limera1n step
- Linux box for the iBEC plus ramdisk plus SSH steps (see `pipeline.md`)
- Patched kernelcache from `tools/kc-patch.py` staged in Legacy-iOS-Kit's cache dir

You don't need the bruteforce binary or the keybag plist. Just a writable mount of the data partition and a way to round-trip a small file through SCP.

## Procedure

### 1. Boot the SSH ramdisk

Same dance as `pipeline.md`. DFU on Mac, limera1n, cable swap to Linux, `bash restore.sh --sshrd --device=<model>`. iproxy listening on local 6414, forwarding to the iPod's port 22.

### 2. Mount the data partition

```sh
sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1 '/bin/mount.sh'
```

`mount.sh` mounts `/dev/disk0s1s2` on `/mnt2` as read-write by default, with the `protect` flag enabled. The plist we want is class 4, so `protect` doesn't block us.

### 3. Pull the plist out

```sh
sshpass -p alpine scp -P 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1:/mnt2/mobile/Library/Preferences/com.apple.springboard.plist .
```

The file is a binary plist of around 2-3 KB.

### 4. Edit it

Drop the three keys:

```python
import plistlib
with open("com.apple.springboard.plist", "rb") as f:
    p = plistlib.load(f)
for k in ("SBDeviceLockFailedAttempts",
         "SBDeviceLockBlocked",
         "SBDeviceLockBlockTimeIntervalSinceReferenceDate"):
    p.pop(k, None)
with open("com.apple.springboard.plist", "wb") as f:
    plistlib.dump(p, f, fmt=plistlib.FMT_BINARY)
```

Removing the keys is cleaner than zeroing them. SpringBoard treats absent keys the same as the initial-state values.

### 5. Push it back

```sh
sshpass -p alpine scp -P 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  com.apple.springboard.plist \
  root@127.0.0.1:/mnt2/mobile/Library/Preferences/com.apple.springboard.plist
```

Ownership and permissions are preserved by SCP into a `mobile`-owned directory.

### 6. Flush the journal

The ramdisk's busybox doesn't have `sync(8)`. Force a journal commit by remounting read-only:

```sh
sshpass -p alpine ssh -p 6414 \
  -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \
  -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null \
  root@127.0.0.1 'mount -u -o ro /mnt2'
```

Verify the change persisted by SCP-ing the file back and checksumming it against your edited copy. The hashes should match.

### 7. Power-cycle the iPod

Hold Power for 5+ seconds. Device powers off. Press Power again. iOS boots normally, SpringBoard reads the cleaned plist, lock screen shows the standard "Enter passcode" UI with no disabled message.

Enter your PIN. You're in.

## Limitations

- Past iPhone 5s (A7, 2013), the failed-attempts counter is in the Secure Enclave. This technique stops working there.
- If "Erase Data after 10 failed attempts" was on in Settings > General > Passcode, the device wiped itself before you got here. Nothing to recover at that point.
- The data partition needs to be writable. Legacy-iOS-Kit's `mount.sh` mounts it read-write by default. If your tooling mounts read-only, remount with `mount_hfs /dev/disk0s1s2 /mnt2`.
