# Tunisie Telecom DWR-2000M — Optimization Guide

> **For:** New owners of the D-Link DWR-2000M (Tunisie Telecom branded)
> **Firmware:** OpenWrt 21.02.7 `r16847-f8282da11e`, vendor build `1.07ME/TT`
> **Last updated:** 2026-11-12

---

## Table of contents

1. [What this router is](#1-what-this-router-is)
2. [Prerequisites](#2-prerequisites)
3. [Quick start — connect and secure](#3-quick-start--connect-and-secure)
4. [Recommended reading order](#4-recommended-reading-order)
5. [What was optimized (summary)](#5-what-was-optimized-summary)
6. [Files in this folder](#6-files-in-this-folder)
7. [If something breaks](#7-if-something-breaks)

---

## 1. What this router is

The D-Link DWR-2000M is a **4G/LTE Wi-Fi 6 router** sold by Tunisie Telecom.
It is **not** a standard D-Link device — it runs a heavily customized OpenWrt
build (`1.07ME/TT`) with Tunisie Telecom branding, a custom web UI, and
carrier-specific features (SMS, USSD, VoLTE, SIM management).

**Key specs:**
- CPU: MediaTek MT7916 (4-core ARMv8)
- RAM: 627 MB
- WAN: Built-in Quectel 4G LTE modem (Ooredoo Tunisia, APN `internet.tn`)
- Wi-Fi: Wi-Fi 6, 2.4 GHz + 5 GHz (2x2)
- LAN: 192.168.1.1/24, DHCP pool 192.168.1.100–249
- Admin UI: `https://192.168.1.1/cgi-bin/luci/`

**Default credentials:** username `admin`, password printed on the device label.

---

## 2. Prerequisites

### All platforms

| Requirement | How to check | Notes |
|---|---|---|
| **Python 3.7+** | `python3 --version` (Linux/macOS) or `python --version` (Windows) | No third-party packages needed — stdlib only |
| **Network access to router** | `ping 192.168.1.1` or open `https://192.168.1.1/` in browser | Must be on the same LAN (Wi-Fi or Ethernet) |
| **Admin password** | Printed on device label | Default is on the sticker under the router |
| **batch-a.py** | Download from this repo | The remediation script |

### Platform-specific notes

**Linux (Ubuntu/Debian):**
```bash
sudo apt install python3
```

**macOS:**
```bash
brew install python3
# or use the system Python: /usr/bin/python3
```

**Windows:**
1. Download Python from https://www.python.org/downloads/
2. During installation, check **"Add Python to PATH"**
3. Verify: open Command Prompt and run `python --version`
4. If `python` doesn't work, try `py --version` or `python3 --version`

### SSH access (optional, for advanced fixes)

SSH is **disabled by default** on this router. To enable it:
1. Run `python3 batch-a.py --step 9` (enables SSH via the vendor toggle)
2. Or manually: More → System → Service → SSH Switch → enable

**SSH clients by platform:**
- **Linux/macOS:** built-in `ssh` command
- **Windows 10+:** built-in OpenSSH (enable in Settings → Apps → Optional Features → OpenSSH Client)
- **Windows (older):** PuTTY (https://www.putty.org/) or Windows Terminal

---

## 3. Quick start — connect and secure

### Step 0: Connect
1. Plug in the router, wait 2 minutes for boot
2. Connect to Wi-Fi: SSID `[REDACTED_SSID_2G]` (2.4 GHz) or `[REDACTED_SSID_5G]` (5 GHz)
3. Password: `[REDACTED_WPA_PSK]` (change this immediately!)
4. Open browser: `https://192.168.1.1/cgi-bin/luci/`
5. Login with `admin` / (password on device label)

### Step 1: Change the admin password (do this first)
More → System → **Password** → enter current password → new password (20+ chars) → Save

### Step 2: Run the remediation script

**Linux / macOS (Bash):**
```bash
export ROUTER_PW='your-new-password'
cd /path/to/batch-a.py
python3 batch-a.py --dry-run    # preview (touches nothing)
python3 batch-a.py --step 1     # apply first fix
python3 batch-a.py --verify     # check state
```

**Windows (Command Prompt):**
```cmd
set ROUTER_PW=your-new-password
cd C:\path\to\batch-a.py
python batch-a.py --dry-run
python batch-a.py --step 1
python batch-a.py --verify
```

**Windows (PowerShell):**
```powershell
$env:ROUTER_PW = "your-new-password"
cd C:\path\to\batch-a.py
python batch-a.py --dry-run
python batch-a.py --step 1
python batch-a.py --verify
```

> **Note:** On Windows, replace `python3` with `python` in all commands.
> If `python` doesn't work, try `py` (the Python launcher).

### Step 3: Run all remediation steps

**Linux / macOS:**
```bash
# Security (no disruption)
python3 batch-a.py --step 1     # firewall + SSH wildcard
python3 batch-a.py --step 8     # adblock disable

# Performance (no disruption)
python3 batch-a.py --step 10    # vendor QoS per-client limits
python3 batch-a.py --step 6     # flow offloading

# Correctness (minor disruption)
python3 batch-a.py --step 7     # disable IPv6 on LAN
python3 batch-a.py --step 2     # rebind protection

# Hygiene (no disruption)
python3 batch-a.py --step 3     # disable debug daemons
python3 batch-a.py --step 11    # DNS consistency
python3 batch-a.py --step 12    # disable collectd
python3 batch-a.py --step 13    # delete DDNS placeholders

# Enable SSH (gateway to advanced fixes)
python3 batch-a.py --step 9     # SSH switch on

# Wi-Fi bundle (DISRUPTS ALL CLIENTS — do in one sitting)
python3 batch-a.py --step 4     # TKIP → CCMP
python3 batch-a.py --step 5     # widths/channels

# Verify everything
python3 batch-a.py --verify
```

**Windows (Command Prompt / PowerShell):** same commands, replace `python3` with `python`.

### Step 4: Fix cosmetic items via web UI
- **SSIDs:** My Wi-Fi → Basic Settings → rename from `[REDACTED_SSID_2G]`/`[REDACTED_SSID_5G]`, set different passwords per band
- **Hostname:** More → System → (hostname field) → change from `MobileRouter`
- **Timezone:** More → System → Network Time → set to `Africa/Tunis`
- **Guest network:** My Wi-Fi → Guest → enable with a password (isolated, vendor-built)

---

## 4. Recommended reading order

If you want to understand what was done and why:

| Order | File | What it covers | Lines |
|---|---|---|---|
| 1 | **This file (README)** | Quick start and overview | ~220 |
| 2 | `dlink-ui-guide.md` | The vendor's custom web UI — where every setting actually lives | 193 |
| 3 | `batch-a-guide.md` | The remediation script — 13 steps, how to run, troubleshooting | 319 |
| 4 | `router-audit-report.md` | Full audit — 26 findings with evidence, methodology, all extracted data | 701 |

Start with this README and `dlink-ui-guide.md` if you just want to optimize your router.
Read `router-audit-report.md` if you want the full technical deep-dive.

---

## 5. What was optimized (summary)

### Security (fixed)
- ✅ Admin UI fenced to LAN zone (was exposed to WAN via wildcard rules)
- ✅ SSH wildcard reject rule disabled (was blocking SSH from everywhere)
- ✅ Password auth enabled in dropbear (was off, contradictory with RootPasswordAuth=on)
- ✅ DNS rebind protection enabled
- ✅ Debug daemons disabled (wfa_dut, meta_tst, telnetd, vsftpd, xl2tpd, easycwmpd)
- ✅ Adblock disabled (was enabled with zero source lists)
- ✅ DDNS placeholder entries deleted
- ⚠️ `/etc/config/system` is world-writable (`chmod o+rw` in rc.local) — needs SSH to fix

### Performance (fixed)
- ✅ TKIP removed from both radios (was capping 5 GHz at 802.11g speeds)
- ✅ 2.4 GHz width: 40 MHz → 20 MHz (was overlapping neighbour on ch4)
- ✅ 5 GHz width: 160 MHz → 80 MHz (was on DFS channel with detection off)
- ✅ 5 GHz channel: auto → 36 (non-DFS)
- ✅ Flow offloading enabled (load was 8.5 on 4 cores)
- ✅ Vendor QoS: per-client caps 3000/1500 kbps (prevents single device saturating link)
- ✅ Collectd disabled (was writing RRD to RAM every 30s)

### Correctness (fixed)
- ✅ IPv6 disabled on LAN (wan6 was dead, clients got ULA with no route)
- ✅ DNS policy made consistent (removed custom option 6 override)
- ✅ 5 GHz radio now carries traffic (was 0 bytes since boot)

### Not fixed (no UI or requires shell)
- ⚠️ PMF (802.11w) disabled — no UI option
- ⚠️ Client isolation disabled — no UI option
- ⚠️ DTIM period = 1 (battery drain) — no UI option
- ⚠️ DFS detection disabled on 5 GHz — no UI option

### Cosmetic (do via web UI)
- SSIDs: `[REDACTED_SSID_2G]` / `[REDACTED_SSID_5G]` → rename
- Hostname: `MobileRouter` → rename
- Timezone: `Etc/GMT-1` → `Africa/Tunis`
- Guest network: disabled → enable with password

---

## 6. Files in this folder

| File | Purpose | Lines |
|---|---|---|
| `README.md` | This file — quick start and overview | ~220 |
| `batch-a.py` | Remediation script (13 steps, ubus API) | ~600 |
| `batch-a-guide.md` | How to run batch-a.py, step descriptions, troubleshooting | 319 |
| `dlink-ui-guide.md` | Vendor web UI navigation guide (corrected paths) | 193 |
| `router-audit-report.md` | Full audit report (26 findings, evidence, methodology) | 701 |

---

## 7. If something breaks

### SSH is locked out
- The web UI still works: `https://192.168.1.1/cgi-bin/luci/`
- Login as `admin` (or `root`) and re-enable SSH: More → System → Service → SSH Switch
- Or re-run: `python3 batch-a.py --step 9` (Linux/macOS) or `python batch-a.py --step 9` (Windows)

### Wi-Fi stopped working
- My Wi-Fi → Basic Settings → check that both 2.4G and 5G are enabled
- If security shows WPA-PSK/WPA2-PSK, set to WPA2-PSK manually
- Re-run: `python3 batch-a.py --step 4` and `--step 5`

### Internet stopped working
- More → Mobile → check APN is `internet.tn`, network type is 3/4/5G
- Check SIM card is seated properly
- Reboot: More → System → Reboot

### A setting didn't take effect
- Some changes need a service restart. Via SSH: `/etc/init.d/<service> restart`
- Firewall changes: `/etc/init.d/firewall reload`
- Network changes: `/etc/init.d/network restart`
- Wi-Fi changes: `wifi reload`

### SSH access (Windows)

**Windows 10/11 (built-in OpenSSH):**
1. Open Settings → Apps → Optional Features → OpenSSH Client → Install
2. Open Command Prompt or PowerShell
3. Run: `ssh admin@192.168.1.1`

**Windows (PuTTY):**
1. Download PuTTY from https://www.putty.org/
2. Enter `192.168.1.1` as host, port 22, connection type SSH
3. Login as `admin` with your password

### Full reset (last resort)
- More → System → Backup/Reset → Restore Factory Settings
- This wipes ALL changes including UCI. You'll need to re-run the remediation.

### Reboot schedule
Three daily reboots are configured (12 AM, 3 AM, 6 PM) via cron.
To remove: `ssh admin@192.168.1.1` then `echo "" > /etc/crontabs/root; /etc/init.d/cron restart`

---

## Important notes

- **No undo.** `uci revert` and `uci rollback` are ACL-denied on this firmware.
  Take a backup first: More → System → Backup/Reset → Generate archive.
- **Wi-Fi changes disconnect all clients.** Steps 4 and 5 bounce both radios.
- **Session expiry.** The web UI session expires after ~10 minutes of idle.
  The script re-logs in for each invocation.
- **SSH password.** Dropbear was configured with `PasswordAuth=off` +
  `RootPasswordAuth=on`. Step 9 sets `PasswordAuth=on`. Test while the web UI
  is still open in case it doesn't work.
- **Two UID-0 accounts.** Both `root` and `admin` have UID 0. The web UI
  logs in as `admin`. If you delete `admin`, you must use `root` instead.

---

*Audit performed 2026-11-08. Remediation applied 2026-11-09 to 2026-11-12.*
*No configuration was modified without user confirmation. All changes were*
*verified against runtime state (iptables, UCI, init list) after application.*
