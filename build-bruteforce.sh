#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 shabier and the pwnboot contributors.
#
# End-to-end build of Sogeti's bruteforce binary on modern macOS
# (Apple Silicon, Xcode 26.x, no old SDK needed).
#
# What this does:
#   1. Clone iphone-dataprotection if you don't have it.
#   2. Apply two source patches that are mandatory for modern compile:
#      - Replace deprecated `kIOMasterPortDefault` symbol with literal `0`
#      - Uncomment the `patch_IOAESAccelerator()` call (Sogeti shipped it
#        commented out)
#   3. Build with current clang + iPhoneOS SDK (whatever Xcode/Theos provides).
#   4. Post-link: convert LC_MAIN -> LC_UNIXTHREAD via lc_main_to_unixthread.py
#      so iOS 5 dyld can load it.
#   5. ldid sign with Sogeti's entitlements.plist.
#
# Output:
#   build/bruteforce-fixed     # ready to scp into an SSH ramdisk
#
# Requirements:
#   - clang (Xcode CLT or Homebrew llvm)
#   - ldid (`brew install ldid`)
#   - python3
#   - An iPhoneOS SDK at $IPHONEOS_SDK (defaults to a Theos sdks dir if $THEOS
#     is set). Modern SDK is fine: minimum target is iOS 6.0 (lowest the
#     linker accepts), and the LC_UNIXTHREAD patch handles the iOS-5 runtime.
#
# Tested with:
#   - macOS Tahoe (26.2), M-series Mac
#   - clang from Xcode 26.x CLT
#   - $THEOS/sdks/iPhoneOS16.5.sdk
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Configuration ----------------------------------------------------------
SOGETI_REPO="${SOGETI_REPO:-$HOME/iphone-dataprotection}"
SOGETI_URL="${SOGETI_URL:-https://github.com/dinosec/iphone-dataprotection.git}"
BUILD_DIR="${BUILD_DIR:-$SCRIPT_DIR/build}"

# Pick an iPhoneOS SDK. Theos's SDKs work; so does Xcode's.
if [ -z "${IPHONEOS_SDK:-}" ]; then
  if [ -n "${THEOS:-}" ]; then
    IPHONEOS_SDK=$(ls -d "$THEOS"/sdks/iPhoneOS*.sdk 2>/dev/null | sort -V | tail -1 || true)
  fi
fi
if [ -z "${IPHONEOS_SDK:-}" ] || [ ! -d "$IPHONEOS_SDK" ]; then
  echo "error: set \$IPHONEOS_SDK to a valid iPhoneOS SDK directory."
  echo "       Theos SDKs (https://github.com/theos/sdks) work fine."
  exit 1
fi
echo "Using SDK: $IPHONEOS_SDK"

# ldid for ad-hoc signing. Sogeti's entitlements include com.apple.keystore.device,
# task_for_pid-allow, etc., which the patched kernel honours at runtime.
LDID="${LDID:-$(command -v ldid || echo /opt/homebrew/bin/ldid)}"
[ -x "$LDID" ] || { echo "error: ldid not found (brew install ldid)"; exit 1; }

# ---- 1. Clone source --------------------------------------------------------
if [ ! -d "$SOGETI_REPO" ]; then
  echo "cloning iphone-dataprotection -> $SOGETI_REPO"
  git clone --depth=1 "$SOGETI_URL" "$SOGETI_REPO"
fi

# ---- 2. Apply source patches (idempotent) -----------------------------------
RT="$SOGETI_REPO/ramdisk_tools"
echo "patching Sogeti source..."

# 2a. Modern macOS SDK marks kIOMasterPortDefault unavailable on iOS. The
# symbol literally resolves to 0 at runtime; replace references with the
# literal so the SDK headers stop blocking us.
grep -rl "kIOMasterPortDefault" "$RT" --include="*.c" --include="*.h" 2>/dev/null \
  | xargs sed -i '' 's/kIOMasterPortDefault/0/g' 2>/dev/null || \
grep -rl "kIOMasterPortDefault" "$RT" --include="*.c" --include="*.h" 2>/dev/null \
  | xargs sed -i 's/kIOMasterPortDefault/0/g' 2>/dev/null || true

# 2b. Sogeti shipped the runtime kernel-patch call commented out. Re-enable.
sed -i '' 's|//patch_IOAESAccelerator();|patch_IOAESAccelerator();|' \
  "$RT/IOAESAccelerator.c" 2>/dev/null || \
sed -i 's|//patch_IOAESAccelerator();|patch_IOAESAccelerator();|' \
  "$RT/IOAESAccelerator.c" 2>/dev/null || true

# Symlink IOKit headers from the SDK into the source tree (Sogeti's includes
# expect a local "IOKit" dir).
ln -snf "$IPHONEOS_SDK/System/Library/Frameworks/IOKit.framework/Headers" "$RT/IOKit"

# ---- 3. Compile -------------------------------------------------------------
mkdir -p "$BUILD_DIR"
cd "$RT"

SRCS=(
  systemkb_bruteforce.c
  AppleKeyStore.c AppleEffaceableStorage.c IOKit.c IOAESAccelerator.c
  util.c registry.c AppleKeyStore_kdf.c device_info.c kernel_patcher.c
  bsdcrypto/pbkdf2.c bsdcrypto/sha1.c bsdcrypto/rijndael.c bsdcrypto/key_wrap.c
  ioflash/ioflash.c ioflash/IOFlashPartitionScheme.c
)

echo "compiling bruteforce (armv7)..."
clang -arch armv7 \
  -isysroot "$IPHONEOS_SDK" \
  -miphoneos-version-min=6.0 \
  -Wl,-no_pie -Wl,-e,_start \
  -framework CoreFoundation -framework IOKit -framework Security \
  -I. -O3 -Wno-pointer-sign \
  -o "$BUILD_DIR/bruteforce" \
  "$SCRIPT_DIR/tools/start.S" "${SRCS[@]}"

# ---- 4. LC_MAIN -> LC_UNIXTHREAD --------------------------------------------
echo "post-link: rewriting LC_MAIN -> LC_UNIXTHREAD..."
python3 "$SCRIPT_DIR/tools/lc_main_to_unixthread.py" \
  "$BUILD_DIR/bruteforce" "$BUILD_DIR/bruteforce-fixed"

# ---- 5. Sign with entitlements ----------------------------------------------
echo "signing with Sogeti entitlements..."
"$LDID" -S"$RT/entitlements.plist" "$BUILD_DIR/bruteforce-fixed"

ls -la "$BUILD_DIR/bruteforce-fixed"
echo
echo "ready: $BUILD_DIR/bruteforce-fixed"
echo
echo "To use:"
echo "  scp -P 6414 -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedKeyTypes=+ssh-rsa \\"
echo "    $BUILD_DIR/bruteforce-fixed root@127.0.0.1:/var/root/bruteforce"
echo "  ssh ... root@127.0.0.1 'chmod +x /var/root/bruteforce; /var/root/bruteforce -u'"
echo
echo "(See docs/pipeline.md for the full SSH-ramdisk + iproxy setup.)"
