# Motorola Moto G24 Power (`fogorow`)

| | |
|---|---|
| Models | XT2425-x (tested: XT2425-1, software channel RETAR) |
| SoC | MediaTek Helio G85 (platform `mt6768`), 8 cores, arm64 |
| RAM / storage | 4 or 8 GB / 128 GB (tested: 8 GB) |
| Battery | 6000 mAh, 30 W charging |
| Android tested | 14 (`UTAS34.82-126-5`) |
| Treble | yes, A/B slots |

## Path A

✅ Works (steps 0–10 tested). Nothing device-specific was needed.

## Path B (unlock + custom ROM): not done, notes only

Status as of October 2026, from public forums. **Verify before trying anything.**

- **No official LineageOS.** The only option is a **GSI** (Generic System Image: a "one size fits
  most" Android build such as LineageOS, crDroid or PixelOS GSIs for arm64 A/B). Some hardware may not work.
- **Bootloader unlock is the hard part.** XDA users describe an unofficial method for this
  MediaTek phone (an `mtkclient` fork using an exploit), with mixed results depending on firmware
  version. Whether Motorola's official unlock program accepts this model is unconfirmed.
- On the tested phone `sys.oem_unlock_allowed = 0`.

References:
- [XDA forum: Moto G24 / G24 Power](https://xdaforums.com/f/motorola-moto-g24-g24-power.12831/)
- [XDA: install custom ROM on G24 / G24 Power](https://xdaforums.com/t/guide-install-custom-rom-on-motorola-g24-g24-power.4792453/)
- [XDA: FOSS bootloader unlock method](https://xdaforums.com/t/foss-method-motorola-moto-g24-g24-power-bootloader-unlock.4760067/)

Before Path B: back up everything, and download the exact stock firmware for your model and
channel so you can restore it.

## Notes for an always-plugged phone

Being plugged in 24/7 at 100% can swell a lithium battery over time. Without root you can't cap
charging from software, and **this model has no built-in charge limit** (checked Settings > Battery
and the hidden settings on Android 14: only Battery saver and Battery manager). Step 10 solves it
with a Wi-Fi smart plug (Tuya / Smart Life) that the phone switches off at 80% and on at 30%
(tested with a metering plug, protocol 3.5). Without a plug, the status panel reminds you to do it
by hand at those levels.
Keep the phone somewhere cool and out of its case, and check it now and then for bulging.
