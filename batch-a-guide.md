# batch-a.py — DWR-2000M Remediation Driver

## What it is

`batch-a.py` is a Python script that applies configuration changes to the D-Link
DWR-2000M router (`MobileRouter`) by talking to the router's own **ubus JSON-RPC
API** — the same interface the LuCI web UI uses internally. It requires no shell
access, no SSH, and no installed packages.

It was written because this firmware's web UI is heavily customised (Tunisie
Telecom branding) and hides or removes many standard OpenWrt settings. The ubus
API exposes the full UCI configuration tree that the UI doesn't.

## Requirements

- Python 3.7+ on your laptop
- Network access to the router (LAN, `192.168.1.1`)
- The router's admin password

No third-party Python packages are needed — only the standard library.

## Quick start

```bash
cd /home/unknown/projects/cli/cliProject1

# 1. Set the password (never hardcode it in the script)
export ROUTER_PW='your-admin-password'

# 2. Preview everything without touching the router
python3 batch-a.py --dry-run

# 3. Apply one step at a time
python3 batch-a.py --step 1

# 4. Verify the result
python3 batch-a.py --verify
```

**Windows (Command Prompt):**
```cmd
cd C:\path\to\batch-a.py
set ROUTER_PW=your-admin-password
python batch-a.py --dry-run
python batch-a.py --step 1
python batch-a.py --verify
```

**Windows (PowerShell):**
```powershell
cd C:\path\to\batch-a.py
$env:ROUTER_PW = "your-admin-password"
python batch-a.py --dry-run
python batch-a.py --step 1
python batch-a.py --verify
```

> On Windows, replace `python3` with `python` in all commands.

## Command-line options

| Flag | Description |
|---|---|
| `--dry-run` | Show what would change and read live state. **Touches nothing.** |
| `--step N` | Apply step N (1–10). Implies a post-change `--verify`. |
| `--verify` | Re-read all settings and print a status report. No changes. |

If neither `--step` nor `--verify` is given, the script runs `--verify` by default.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ROUTER_PW` | *(required)* | Admin password. Read from env, never stored in the script. |
| `ROUTER_USER` | `admin` | Username (rarely needs changing). |

## The 10 steps

Each step is independent and can be run in any order. Steps that change Wi-Fi
settings (4, 5) will disconnect all clients.

### Step 1 — Firewall: fence admin UI to LAN

**Finding:** C1 (critical) + C2 (SSH wildcard)
**What it does:**
- Changes `firewall.cfg1292bd` (http, dport 80) and `cfg1392bd` (https, dport 443)
  from `src=*` to `src=lan`. This makes the zone-specific `http_wan`/`https_wan`
  REJECT rules effective instead of dead code.
- Disables `firewall.cfg1192bd` (ssh, src=*) which was a wildcard REJECT sitting
  in the base INPUT chain before the zone jumps, blocking SSH from everywhere
  including LAN.

**Disruption:** None.
**Verify:** `iptables-save | grep 'dport 80\|dport 443\|dport 22'` — no rules
should appear in the base `-A INPUT` chain.

### Step 2 — DNS rebind protection

**Finding:** M7 (medium)
**What it does:** Sets `dhcp.@dnsmasq[0].rebind_protection='1'`.
**Disruption:** None.
**Status:** Already applied (was set before this script ran).

### Step 3 — Disable debug/test daemons

**Finding:** C3 (critical)
**What it does:** Disables six vendor debug services:
- `wfa_dut` (Wi-Fi Alliance DUT test mode)
- `meta_tst` (vendor test harness)
- `telnetd` (plaintext remote shell)
- `vsftpd` (FTP server)
- `xl2tpd` (L2TP VPN server)
- `easycwmpd` (TR-069 agent)

Deliberately excluded (may be load-bearing): `atd`, `atcid`, `atci_service`
(SMS/USSD), `ql_netd`, `ql_ril_service`, `mnld`, `scd`, `thermal_core`,
`mipc_*` (modem/thermal).

**Disruption:** None. Telnet/FTP become unavailable (they were firewalled anyway).

### Step 4 — Wi-Fi: drop TKIP / WPA1 mixed mode

**Finding:** H3 (high)
**What it does:** Sets `encryption='psk2+ccmp'` on both `ra0` (2.4 GHz) and
`rai0` (5 GHz). Removes TKIP and WPA1 mixed mode, restoring Wi-Fi 6 rates.
**Disruption:** **Yes — all Wi-Fi clients disconnect.** Do in one sitting with
step 5.
**Status:** Already applied.

### Step 5 — Wi-Fi: fix channel widths and pin channels

**Finding:** H5, H6 (high)
**What it does:**
- 2.4 GHz: `htmode` HE40→HE20, `ht_coex` 0→1, channel pinned to 6
- 5 GHz: `htmode` HE160→HE80, channel pinned to 36 (non-DFS)
**Disruption:** **Yes — all Wi-Fi clients disconnect.**
**Status:** Already applied.

### Step 6 — Enable flow offloading

**Finding:** M1 (medium)
**What it does:** Sets `firewall.@defaults[0].flow_offloading='1'` and
`flow_offloading_hw='1'`. Reduces CPU cost of packet forwarding.
**Disruption:** None.
**Status:** Already applied.

### Step 7 — Disable IPv6 on LAN

**Finding:** M6 (medium)
**What it does:** Removes `ip6assign` from the LAN interface, disables DHCPv6
and Router Advertisements. Prevents clients from getting ULA addresses with no
route to the internet.
**Disruption:** IPv6-only clients lose connectivity (rare). Most clients fall
back to IPv4 automatically.

### Step 8 — Disable adblock

**Finding:** L1 (low)
**What it does:** Sets `adblock.global.adb_enabled='0'`. Adblock was enabled
but had zero source lists configured — filtering nothing while consuming
memory and startup time.
**Disruption:** None.

### Step 9 — Enable SSH

**Finding:** M5 (medium)
**What it does:**
1. Calls the vendor endpoint `admin/more/ssh_switch?ssh_switch=on`
2. Ticks the LAN checkbox in Remote Management (`ssh: 10`)
3. Disables the wildcard SSH reject rule (`cfg1192bd`)
4. Sets `dropbear.PasswordAuth='on'` (was off, contradicting RootPasswordAuth=on)

**SSH access after step 9:**

- **Linux/macOS:** `ssh admin@192.168.1.1`
- **Windows 10/11:** Enable OpenSSH Client (Settings → Apps → Optional Features), then `ssh admin@192.168.1.1` in Command Prompt or PowerShell
- **Windows (PuTTY):** Host `192.168.1.1`, port 22, connection type SSH, login as `admin`
**Disruption:** None (SSH was already unreachable).
**Note:** Test the password while the web UI is still open. If dropbear rejects
it, you can still fix things via the web UI or ubus.

### Step 10 — Vendor QoS (M2 stopgap)

**Finding:** M2 (medium)
**What it does:** Configures the vendor's per-client rate limiter via
`admin/status/qos_limit_set`. Reads DHCP leases and caps each client to
**3000 kbps down / 1500 kbps up**.

**Why these values:**
- **Upload (1500 kbps):** The uplink is only 16 Mbps. With 8 clients, even
  2000 kbps each would saturate it. 1500 leaves headroom for ACKs and
  concurrent uploads.
- **Download (3000 kbps):** The downlink is 51 Mbps. 3000 per client means
  max 24 Mbps with 8 simultaneous downloaders, leaving 27 Mbps free. A single
  heavy downloader can't crowd out others.
- **Why upload matters more:** Saturated upload delays TCP ACKs, which slows
  downloads for everyone. It also freezes video calls and stalls web page
  loads (DNS + HTTP requests queue behind uploads).

**Why not real SQM:** This device cannot run SQM/cake. Investigation showed:
- `sqm-scripts` package: not available (OpenWrt 21.02.7 repos for this
  architecture return 404)
- `kmod-sched-cake` / `kmod-sched-fq_codel`: not in kernel config
- `tc` binary: not installed
- Real SQM would require cross-compilation from source

The vendor QoS is per-client rate limiting, not queue management. It prevents
any single client from saturating the 16 Mbps uplink.
**Disruption:** None. Limits take effect immediately for new connections.

### Step 11 — DNS consistency

**Finding:** M8 (medium)
**What it does:** Removes the custom DHCP option 6 override
(`6,94.140.14.15,185.228.168.168`) from the LAN DHCP section. Clients now
use the router (dnsmasq) as their DNS resolver, which forwards to the router's
upstream DNS (ISP + Google). This makes the DNS policy consistent across all
clients and enables dnsmasq's caching and rebind protection.
**Disruption:** None. Clients pick up the new DNS on next DHCP renewal.

### Step 12 — Disable collectd / luci_statistics

**Finding:** L2 (low)
**What it does:** Disables the `collectd` and `luci_statistics` init scripts.
These were writing RRD data to `/tmp` (RAM) every 30 seconds on an already-loaded
CPU, and the data was lost on reboot.
**Disruption:** None. Statistics graphs in LuCI stop updating.

### Step 13 — Delete DDNS placeholder entries

**Finding:** L3 (low)
**What it does:** Deletes `myddns_ipv4` and `myddns_ipv6` sections from the
ddns config, which contained placeholder values (yourhost.example.com,
your_username, your_password).
**Disruption:** None. DDNS was not enabled.
**What it does:** Configures the vendor's per-client rate limiter via
`admin/status/qos_limit_set`. Reads DHCP leases and caps each client to
4000 kbps down / 2000 kbps up.

**Why not real SQM:** This device cannot run SQM/cake. Investigation showed:
- `sqm-scripts` package: not available (OpenWrt 21.02.7 repos for this
  architecture return 404)
- `kmod-sched-cake` / `kmod-sched-fq_codel`: not in kernel config (only
  HFSC and TBF, as modules)
- `tc` binary: not installed
- `/proc/sys/net/*` reads: ACL-blocked

The vendor QoS is per-client rate limiting, not queue management. It prevents
any single client from saturating the 16 Mbps uplink, keeping navigation
responsive during uploads. It does not prevent bufferbloat the way SQM would.

**Disruption:** None.

## Recommended run order

```bash
export ROUTER_PW='your-password'
cd /home/unknown/projects/cli/cliProject1

# 1. Security fixes (no disruption)
python3 batch-a.py --step 1    # firewall src=lan + ssh wildcard
python3 batch-a.py --step 8    # adblock disable

# 2. Performance (no disruption)
python3 batch-a.py --step 10   # vendor QoS per-client limits
python3 batch-a.py --step 6    # flow offloading (already done)

# 3. Correctness (minor disruption)
python3 batch-a.py --step 7    # disable IPv6 on LAN
python3 batch-a.py --step 2    # rebind protection (already done)

# 4. Hygiene (no disruption)
python3 batch-a.py --step 3    # disable debug daemons
python3 batch-a.py --step 8    # adblock disable
python3 batch-a.py --step 11   # DNS consistency
python3 batch-a.py --step 12   # disable collectd
python3 batch-a.py --step 13   # delete DDNS placeholders

# 5. Enable SSH (gateway to advanced fixes)
python3 batch-a.py --step 9    # SSH switch on

# 6. Wi-Fi bundle (DISRUPTS ALL CLIENTS — do in one sitting)
python3 batch-a.py --step 4    # TKIP -> CCMP
python3 batch-a.py --step 5    # widths/channels

# 7. Verify everything
python3 batch-a.py --verify
```

## How it works internally

1. **Login:** POSTs `luci_username`/`luci_password` to `/cgi-bin/luci`, extracts
   the `sysauth` session cookie.
2. **UCI changes:** Calls `uci set` with a `values` object (this rpcd build
   requires an object, not individual option/value pairs), then `uci apply`
   (commit + service reload). Note: `uci revert` and `uci rollback` are
   ACL-denied on this firmware — changes are one-way.
3. **Vendor endpoints:** Calls the custom JSON endpoints under
   `/cgi-bin/luci/admin/...` (e.g., `admin/more/ssh_switch`,
   `admin/status/qos_limit_set`) that the branded UI uses internally.
4. **Verification:** Re-reads UCI state and greps the runtime `iptables-save`
   output to confirm changes actually reached the kernel.

## Important caveats

- **No undo.** `uci revert` and `uci rollback` are ACL-denied. Take a backup
  first via More → System → Backup/Reset.
- **Wi-Fi changes disconnect all clients.** Steps 4 and 5 bounce both radios.
- **SSH password.** Dropbear was configured with `PasswordAuth=off` +
  `RootPasswordAuth=on` (contradictory). Step 9 sets `PasswordAuth=on`.
  Test while the web UI is still open.
- **Session expiry.** The `sysauth` cookie expires after ~10 minutes of idle
  time. The script re-logs in for each invocation. For long operations, run
  steps individually.
- **One-way apply.** `uci apply` commits and reloads services. There is no
  timeout-based rollback on this firmware.

## Files

| File | Purpose |
|---|---|
| `batch-a.py` | The remediation script (this document describes it) |
| `router-audit-report.md` | Full audit report with all findings and evidence |
| `dlink-ui-guide.md` | Guide to the vendor's customised web UI |

## Troubleshooting

**"set ROUTER_PW first"** — The script requires the password in the environment.
Run `export ROUTER_PW='your-password'` before invoking (Linux/macOS).
On Windows: `set ROUTER_PW=your-password` (CMD) or `$env:ROUTER_PW = "your-password"` (PowerShell).

**Login fails** — Check that the router is reachable: `curl -sk https://192.168.1.1/`.
If you changed the password via the web UI, update `ROUTER_PW`.

**Apply returns status 5** — This means "no data" / "no pending changes". It
usually means the change was already applied. Check with `--verify`.

**SSH still closed after step 9** — The vendor's SSH toggle may need a reboot
to take effect. Try `reboot` via the web UI (More → System → Reboot) or
`python3 batch-a.py --step 9` again after reboot.

**Verify shows LEAK rules** — If `raw -A INPUT dport 80/443` is non-zero after
step 1, the firewall reload didn't pick up the change. Try:
`ssh admin@192.168.1.1` then `/etc/init.d/firewall restart`.
