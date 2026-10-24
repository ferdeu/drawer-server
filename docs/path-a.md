# Path A: server on stock Android (nothing erased)

`bash setup.sh` runs all of this for you. This page explains what each step does, so you know what's
happening and can fix it if something goes wrong.

**Why "Path A"?** There are two ways to turn a phone into a server:

- **Path A** (this one): keep the phone's normal Android and add a Linux environment on top (Termux).
  No unlocking, no erasing, low risk. Limits: no "root" (admin) access, so programs can't use ports
  below 1024 (for example DNS on port 53), and you can't cap battery charging from software.
- **Path B**: unlock the bootloader and install a different system (like LineageOS) plus root. Full
  control, but it erases the phone, may void the warranty, and on some phones it's risky or impossible.
  See the notes for your device in [devices/](devices/).

Start with A. You can always go to B later.

---

## Step 0: look at the phone

`scripts/00-recon.sh` (read-only)

On the phone:

1. **Settings → About phone** → tap **Build number** 7 times. Enter your PIN. "You are now a developer!"
2. **Settings → System → Developer options** → turn on **USB debugging**.
   Developer options being on is *not* enough: USB debugging is a separate switch inside that menu.
3. Plug the phone into the computer. On the phone: **"Allow USB debugging?"** → check
   *Always allow from this computer* → **Allow**.

"File transfer" mode is not the same thing: it only lets the computer see files, like a USB stick.
`adb` needs USB debugging.

The script prints the model, Android version, RAM, storage and battery. If `adb devices` shows nothing,
toggle USB debugging off and on, tap **Revoke USB debugging authorizations**, and replug the cable.

## Step 1: stop Android from killing background programs

`scripts/01-server-settings.sh` (undo with `--revert`)

Android is built for a phone in your pocket: it kills anything in the background to save battery.
A server must never sleep, so the script:

- turns off the **phantom process killer** (Android 12+ kills "child processes" of apps, and every
  program you run inside Termux is one of those). This is the same as *Developer options →
  Disable child process restrictions*.
- turns off **Adaptive Battery**, which freezes apps you don't open often.

## Step 2: install Termux

`scripts/02-install-termux.sh`

Downloads three apps from **F-Droid** (the free-software app store) and installs them:

| App | What it is |
|---|---|
| **Termux** | a terminal with a small Linux inside, where the server programs live |
| **Termux:Boot** | starts our server automatically when the phone turns on |
| **Termux:API** | lets scripts read battery level, temperature, etc. |

The Play Store version of Termux is old and abandoned. Always use F-Droid (or GitHub releases).
All three must come from the same place, or they refuse to talk to each other.

The script also removes the three apps from battery optimization.

### About the Play Protect warning

You will see this three times (photo from a phone set to Spanish):

<img src="img/play-protect-warning.jpg" alt="Google Play Protect: 'Blocked unsafe app. This app was built for an older version of Android and doesn't include the latest privacy protections.' Options: 'Install anyway' (small text) and 'Got it' (big button)." width="300">

> **Blocked unsafe app.** *This app was built for an older version of Android and doesn't include the
> latest privacy protections.*

Tap the small **"Install anyway"** text. The big **"Got it"** button *cancels* the install.

**Why it appears:** Termux deliberately targets an older Android version, because newer Android
versions forbid apps from running programs they download (and running programs is exactly what
Termux is for). Play Protect flags *that*, not a virus. Termux is open source and the APKs come
straight from f-droid.org.

## Step 3: SSH

`scripts/03-setup-ssh.sh`

**SSH** lets you type commands on the phone from your computer's keyboard, as if you were sitting at it.

1. Creates a key pair on your computer (`~/.ssh/drawer_server_ed25519`). Think of it as a
   key-and-lock set: the computer keeps the key, the phone gets the lock.
2. Copies the lock (public key) and `termux/bootstrap.sh` to the phone's `Download/drawer-server/` folder.
3. Opens Termux and **types** `bash /sdcard/Download/drawer-server/bootstrap.sh` for you.
   **Leave the phone unlocked and on Termux.** The first launch unpacks Linux, so the script waits ~25 s.
4. Inside the phone, the bootstrap installs `openssh`, trusts only your key (password login is off),
   holds a *wake lock* so the CPU doesn't sleep, and creates `~/.termux/boot/10-sshd.sh` so SSH comes back after a reboot.
5. Tests SSH through the USB cable.

Termux's SSH listens on port **8022**, not 22, because ports under 1024 need root.
The Termux username looks like `u0_a281`; it gets saved in `local/phone.env`.

You'll see a permanent notification "Termux: wake lock held". That's how you know it's awake.

## Step 4: home network

`scripts/04-network.sh`

Tests SSH over Wi-Fi (no cable) and tells you what to put in your router so the phone always gets the
same address. That's a **DHCP reservation**: the router hands out addresses like a coat check, and the
reservation tells it "this phone always gets ticket 50".

On a **TP-Link Archer AX23** (tested): *Advanced → Network → DHCP Server → Address Reservation → Add*, type the MAC in the six boxes and the IP, then press **Tab** (the SAVE button stays grey until the IP field loses focus).

About the MAC address: Android invents a different one for each Wi-Fi network (privacy feature), but it
stays the same for *your* network, so reserving the one the script shows works fine.

Weak signal (below about −75 dBm) means a flaky server. Move the phone closer to the router.

## Step 5: Tailscale (access from anywhere)

`scripts/05-tailscale.sh`

From outside home, the usual trick is "open a port on the router". That doesn't work on **Starlink**
and many mobile/fiber providers, because they put lots of homes behind one public address (**CGNAT**),
so nobody outside can reach yours directly.

**Tailscale** creates a private network between your devices that works from anywhere, and it's free
for personal use. The script opens the Play Store for you. Install it, log in, and accept the VPN
permission. Then install Tailscale on your computer or other phone with the same account.

The script also sets Tailscale as the **always-on VPN**, so it reconnects after a reboot. The phone needs a Google account signed in to install from the Play Store.

---

## Undoing everything

```bash
bash scripts/01-server-settings.sh --revert
adb uninstall com.termux.boot && adb uninstall com.termux.api && adb uninstall com.termux
```

Then remove the router reservation, and Tailscale if you want.
