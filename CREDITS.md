# Credits

This repo is connective tissue. The hard work was done by other people.

## The cryptography and on-device tools

[Jean-Baptiste Bédrune and Jean Sigwald (Sogeti ESEC Lab)](https://github.com/dinosec/iphone-dataprotection). The original `iphone-dataprotection` toolkit. `bruteforce.c`, `kernel_patcher.c`, the IOAESAccelerator UID byte pattern, the AKS keybag unwrap, the EMF partition decryptor. Their HITB 2011 talk laid out the full data-protection model.

## limera1n

[George Hotz (geohot)](https://github.com/geohot). The original limera1n bootrom exploit (2010). Heap overflow against the USB stack of S5L8920/8922/8930.

[axi0mX](https://github.com/axi0mX/ipwndfu). Modernized the limera1n implementation in `ipwndfu`, integrated alongside checkm8.

[alfiecg24](https://github.com/alfiecg24/limera1n-pwner). Pure-Python rewrite of the limera1n stage, tested on Apple Silicon Macs. The starting point we used.

## Boot-chain pipeline

[LukeZGD](https://github.com/LukeZGD/Legacy-iOS-Kit). Legacy-iOS-Kit, the actively maintained successor to redsn0w-era jailbreak/recovery tooling. Bundles `xpwntool`, `ldid`, `irecovery`, `iproxy`, the daibutsuCFW kernel patches, and a working SSH-ramdisk boot path for iPod3,1 and friends. We hand it our patched kernelcache; it does everything else.

[daibutsu](https://github.com/dora2-iOS/daibutsuCFW). The CFW patches Legacy-iOS-Kit uses. Their `iBoot32Patcher` and friends are how iBSS/iBEC become tetherable.

## Firmware keys

[The iPhone Wiki firmware keys archive](https://www.theiphonewiki.com/wiki/Firmware_Keys) and the contributors who recovered and published them. Without that, no `xpwntool` decrypt step is possible.

## What this repo adds

- A modern macOS toolchain story that doesn't require Xcode 4.x or an old iOS SDK
- A small Mach-O converter (`lc_main_to_unixthread.py`) for running modern-built armv7 binaries on iOS 5
- An offline kernelcache patcher (`kc-patch.py`) that sidesteps Sogeti's TFP0 dependency
- Documentation of the dead ends from a real recovery in 2026
