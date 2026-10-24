# Services

🚧 Work in progress. Each service will get its own script once it's tested on a real phone.

Ideas on the list (Path A, no root):

| Service | What it's for | Notes |
|---|---|---|
| Minecraft server | a world for the kids on the home Wi-Fi | Java edition via a JVM, or a lightweight server; RAM-hungry |
| Syncthing | automatic photo backup between devices | light, runs well in Termux |
| Jellyfin | "home Netflix" for your own videos | transcoding is heavy on a phone CPU; direct play is fine |
| File share | a shared folder on the home network | e.g. over SFTP (already works with SSH) |
| Bots / scripts 24/7 | anything you want running all the time | Python, Node, cron |
| Status page | battery, temperature, uptime at a glance | uses Termux:API |
| Ad blocker (AdGuard Home) | block ads for the whole house | needs port 53 → root (Path B), or a workaround |

RAM/CPU numbers and "how many fit at once" will be filled in with real measurements.
