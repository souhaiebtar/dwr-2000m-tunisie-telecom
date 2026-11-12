# Tunisie Telecom DWR-2000M — Optimization Guide

> **For:** New owners of the D-Link DWR-2000M (Tunisie Telecom branded)
> **Firmware:** OpenWrt 21.02.7 `r16847-f8282da11e`, vendor build `1.07ME/TT`
> **Last updated:** 2026-11-12

---

## Table of contents

1. [What this router is](#1-what-this-router-is)
2. [Quick start — connect and secure](#2-quick-start--connect-and-secure)
3. [Recommended reading order](#3-recommended-reading-order)
4. [What was optimized (summary)](#4-what-was-optimized-summary)
5. [Files in this folder](#5-files-in-this-folder)
6. [If something breaks](#6-if-something-breaks)

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

## 2. Quick start — connect and secure

### Step 0: Connect
1. Plug in the router, wait 2 minutes for boot
2. Connect to Wi-Fi: SSID `[REDACTED_SSID_2G]` (2.4 GHz) or `[REDACTED_SSID_2G]5` (5 GHz)
3. Password: `[REDACTED_WPA_PSK]` (change this immediately!)
4. Open browser: `https://192.168.1.1/cgi-bin/luci/`
5. Login with `admin` / (password on device label)

### Step 1: Change the admin password (do this first)
More → System → **Password** → enter current password → new password (20+ chars) → Save

### Step 2: Install the remediation script
Copy `batch-a.py` to your laptop. You need Python 3.7+ (no packages required).

```bash
export ROUTER_PW='your-new-password'
cd /path/to/batch-a.py
python3 batch-a.py --dry-run    # preview (touches nothing)
python3 batch-a.py --step 1     # apply first fix
python3 batch-a.py --verify     # check state
```

### Step 3: Run all remediation steps
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

### Step 4: Fix cosmetic items via web UI
- **SSIDs:** My Wi-Fi → Basic Settings → rename from `[REDACTED_SSID_2G]`/`[REDACTED_SSID_2G]5`, set different passwords per band
- **Hostname:** More → System → (hostname field) → change from `MobileRouter`
- **Timezone:** More → System → Network Time → set to `Africa/Tunis`
- **Guest network:** My Wi-Fi → Guest → enable with a password (isolated, vendor-built)

---

## 3. Recommended reading order

If you want to understand what was done and why:

| Order | File | What it covers | Lines |
|---|---|---|---|
| 1 | **This file (README)** | Quick start, overview | ~100 |
| 2 | `dlink-ui-guide.md` | The vendor's custom web UI — where every setting actually lives | 193 |
| 3 | `batch-a-guide.md` | The remediation script — 13 steps, how to run, troubleshooting | 319 |
| 4 | `router-audit-report.md` | Full audit — 26 findings with evidence, methodology, all extracted data | 701 |

Start with this README and `dlink-ui-guide.md` if you just want to optimize your router.
Read `router-audit-report.md` if you want the full technical deep-dive.

---

## 4. What was optimized (summary)

### Security (fixed)
- ✅ Admin UI fenced to LAN zone (was exposed to WAN via wildcard rules)
- ✅ SSH wildcard reject rule disabled (was blocking SSH from everywhere)
- ✅ Password auth enabled in dropbear (was off, contradictory with RootPasswordAuth=on)
- ✅ `/etc/config/system` permissions noted (was world-writable — needs shell to fix)
- ✅ DNS rebind protection enabled
- ✅ Debug daemons disabled (wfa_dut, meta_tst, telnetd, vsftpd, xl2tpd, easycwmpd)
- ✅ Adblock disabled (was enabled with zero source lists)
- ✅ DDNS placeholder entries deleted

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
- ⚠️ `/etc/config/system` is world-writable (`chmod o+rw` in rc.local) — needs SSH
- ⚠️ PMF (802.11w) disabled — no UI option
- ⚠️ Client isolation disabled — no UI option
- ⚠️ DTIM period = 1 (battery drain) — no UI option
- ⚠️ DFS detection disabled on 5 GHz — no UI option
- ⚠️ SSH is now working (enabled via vendor toggle + firewall fix)

### Cosmetic (do via web UI)
- SSIDs: `[REDACTED_SSID_2G]` / `[REDACTED_SSID_2G]5` → rename
- Hostname: `MobileRouter` → rename
- Timezone: `Etc/GMT-1` → `Africa/Tunis`
- Guest network: disabled → enable with password

---

## 5. Files in this folder

| File | Purpose | Lines |
|---|---|---|
| `README.md` | This file — quick start and overview | ~100 |
| `batch-a.py` | Remediation script (13 steps, ubus API) | ~600 |
| `batch-a-guide.md` | How to run batch-a.py, step descriptions, troubleshooting | 319 |
| `dlink-ui-guide.md` | Vendor web UI navigation guide (corrected paths) | 193 |
| `router-audit-report.md` | Full audit report (26 findings, evidence, methodology) | 701 |

---

## 6. If something breaks

### SSH is locked out
- The web UI still works: `https://192.168.1.1/cgi-bin/luci/`
- Login as `admin` (or `root`) and re-enable SSH: More → System → Service → SSH Switch
- Or re-run: `python3 batch-a.py --step 9`

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

### Full reset (last resort)
- More → System → Backup/Reset → Restore Factory Settings
- This wipes ALL changes including UCI. You'll need to re-run the remediation.

### Reboot schedule
Three daily reboots are configured (12 AM, 3 AM, 6 PM) via cron.
To remove: `ssh admin@192.168.1.1 'echo "" > /etc/crontabs/root; /etc/init.d/cron restart'`

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
