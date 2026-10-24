# The ideas, in plain words

For curious people of any age. No prior knowledge needed.

**Server**: a computer that's always on, waiting for others to ask it for things (a web page, a
Minecraft world, your photos). Any computer can be one, including an old phone.

**Why a phone?** It's a small computer: processor, memory, storage, Wi-Fi. It even has a
battery, so if the power goes out it keeps running (servers in big data centers pay a lot for that,
it's called a UPS). And it uses very little electricity.

**adb (Android Debug Bridge)**: a "talking cable" between your computer and the phone. With it, the
computer can install apps, change settings and read information. It only works if you turn on *USB
debugging* and accept the prompt on the phone, so nobody can do it to your phone without you knowing.

**Termux**: an app that puts a small Linux inside Android. Linux is the system most servers in the
world run on. In Termux you install programs with `pkg install <name>`.

**SSH**: a secure way to type commands into another computer from yours. Everything travels
encrypted. We log in with a **key** instead of a password: the computer keeps the private key and the
phone keeps the matching public "lock". Only that computer can get in.

**Port**: a building has one street address but many apartments. A computer has one IP address and
many ports. SSH lives in apartment 8022 in Termux. Apartments below 1024 are "reserved": only the
building manager (root) can use them.

**IP address**: the phone's address on your home network, like `192.168.1.170`. The router hands
them out. A **DHCP reservation** makes the router always give the same one to the same device.

**CGNAT**: your internet company puts many homes behind one shared public address, like a building
with one mailbox for everyone. Mail from outside can't find your apartment on its own. That's why we
use **Tailscale**, a private network that connects your devices from anywhere.

**Wake lock**: a note to Android saying "don't let the processor sleep". Servers can't nap.

**Root**: being the administrator of the phone, allowed to do anything. Android doesn't give you that
by default. Getting it usually means **unlocking the bootloader** (the program that decides which
system starts when you turn the phone on), which erases the phone. Path A skips all of that.

**Bootloader / custom ROM / LineageOS**: if you unlock the bootloader you can replace Android with
another version, like LineageOS: cleaner, updated longer, and easy to root. That's "Path B".
