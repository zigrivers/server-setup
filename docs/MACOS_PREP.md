# macOS Prep — Two Mac Studio Edition

This document covers the macOS-level settings that the click-by-click
HTML guide assumes you have configured. Do these once per machine,
before installing anything in `~/ai`.

## Naming

Pick distinct hostnames so the Thunderbolt link and any future SSH /
mDNS work unambiguously.

```bash
# On Machine 1
sudo scutil --set ComputerName  "mac-studio-1"
sudo scutil --set HostName      "mac-studio-1.local"
sudo scutil --set LocalHostName "mac-studio-1"

# On Machine 2
sudo scutil --set ComputerName  "mac-studio-2"
sudo scutil --set HostName      "mac-studio-2.local"
sudo scutil --set LocalHostName "mac-studio-2"
```

## Sleep

Machine 2 must not sleep — `mlx_lm.server` jobs are killed by App Nap and
display sleep can suspend network activity. Machine 1 can sleep its
display but should not sleep the system while you're driving it.

```bash
# Machine 2 — never sleep system, disk, or display. Also keep awake on AC.
sudo pmset -a sleep 0 disksleep 0 displaysleep 0
sudo pmset -a powernap 0 lidwake 0 womp 1

# Machine 1 — let display sleep after 20 min; never sleep system on AC.
sudo pmset -c sleep 0 displaysleep 20 disksleep 0
sudo pmset -c powernap 0
```

If you want to keep a long task awake without changing pmset globally:

```bash
caffeinate -dimsu -t 7200   # 2 hours, no sleep
```

## iCloud and Documents/Desktop sync

iCloud sync can silently move files under `~/Documents` and `~/Desktop`,
breaking `~/ai/...` paths if the user ever symlinks across. Recommended:

1. **System Settings → [your Apple ID] → iCloud Drive → Drive Folders…**
2. Turn **off** "Desktop & Documents Folders" on both Macs.
3. Keep `~/ai` outside of any iCloud-synced folder. The default
   `~/ai/local-ai-stack` is fine; `~/Documents/ai/...` would not be.

Model weights, agent memory, and the launch logs should never sync.

## FileVault

FileVault is fine. Two considerations:

- After a reboot, FileVault may delay login keychain unlock until you
  log in once. Launchd-autostarted servers (task 07) start on first
  user login, not at boot.
- Make sure the recovery key is stored somewhere safe; you cannot ssh
  in to a locked-down Mac to type the recovery passphrase.

## Firewall

Leave the macOS firewall **off** on both Macs for the duration of
initial setup — model serving over the Thunderbolt link is easier to
debug without it. Once everything works, you can re-enable it and add
incoming exceptions for `mlx_lm.server` if you prefer.

```bash
sudo defaults write /Library/Preferences/com.apple.alf globalstate -int 0
sudo launchctl unload   /System/Library/LaunchDaemons/com.apple.alf.agent.plist 2>/dev/null || true
sudo launchctl unload   /System/Library/LaunchDaemons/com.apple.alf.useragent.plist 2>/dev/null || true
```

Re-enable later:

```bash
sudo defaults write /Library/Preferences/com.apple.alf globalstate -int 1
```

## Remote Login (SSH)

Already covered in the HTML guide §01, but verify on Machine 2:

```bash
sudo systemsetup -getremotelogin       # should print: Remote Login: On
```

## Time and timezone

Make sure both Macs agree on time. Drift breaks log correlation and any
future TLS work.

```bash
sudo systemsetup -setusingnetworktime on
sudo systemsetup -getnetworktimeserver
```

## Power source

The Mac Studios should be on UPS. A mid-inference power cut can corrupt
`~/.cache/huggingface/` partial downloads and leave `mlx_lm.server`
holding wedged sockets.

## Verify

When the macOS prep is done, this should all be true:

| Check | Command | Expected |
|---|---|---|
| Hostname | `scutil --get LocalHostName` | `mac-studio-1` / `mac-studio-2` |
| No sleep on M2 | `pmset -g \| grep ' sleep'` | `0` |
| Time sync on | `systemsetup -getnetworktimeserver` | a server, no error |
| SSH on M2 | `sudo systemsetup -getremotelogin` | `On` |
| Thunderbolt up | `ping -c 1 10.10.10.2` (from M1) | replies |

If everything above is green, you are ready to clone the repo and
start the HTML guide from Part I onwards.
