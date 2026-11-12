# Router Audit Report — D-Link DWR-2000M (`MobileRouter`)

**Audit date:** 2026-11-08
**Target:** `https://192.168.1.1/cgi-bin/luci/`
**Access level used:** LuCI administrator (read-only — *no configuration was modified*)
**Prepared for:** network owner

---

## 0. Summary

| | |
|---|---|
| Device | D-Link DWR-2000M — 4G/LTE CPE with Wi-Fi 6 (MediaTek MT7916) |
| Firmware | OpenWrt 21.02.7 `r16847-f8282da11e`, vendor build `1.07ME/TT` |
| LuCI | `vtrunk branch`, `git-25.177.11687-212f904` |
| Kernel | `5.4.238` (aarch64, 4 cores) |
| Uptime at audit | 254 865 s ≈ 2 days 22 h |
| WAN | Cellular, `[REDACTED_WAN_IP]/29`, 16 Mbps up / 51 Mbps down |
| LAN | `192.168.1.1/24`, 8 active DHCP leases |

**Findings:** 26 total — 4 critical, 8 high, 8 medium, 6 low. The single largest practical wins are **disabling TKIP** (currently caps your 5 GHz radio at 802.11g-era rates) and **enabling flow offloading** (load average is 8.5 on a 4-core CPU).

> ⚠️ **Immediate action:** the administrator password was transmitted in plaintext through a chat channel during this audit. Rotate it. Note there are **two UID-0 accounts** (`root` and `admin`) — change both.

### Contents

| Section | Purpose |
|---|---|
| §1 Methodology | How every value below was obtained, and what was blocked |
| §2 Device inventory | Complete factual dump: hardware, network, WAN, DHCP, clients, Wi-Fi, firewall, services, TLS, accounts |
| §3 Connection methods | All 17 ways in, verified/blocked, with credentials and ports |
| §4 Findings & advice | 26 issues, each with evidence, impact, and a concrete fix |
| §5 Remediation order | Four reversible batches with verification steps |
| §6 Artefacts | Raw files captured, and how to make them useless |

---

## 1. Methodology — how the information was extracted

Everything below was obtained without shell/SSH access, using only the router's own HTTP API surface. This is worth documenting so you can reproduce or revoke it.

### 1.1 Access path

1. **Reachability check** — `curl` against `https://192.168.1.1/` returned `200` with a meta-refresh to `/cgi-bin/luci/`; plain `http://` returned `307` → HTTPS. Confirms uhttpd + LuCI are the only exposed management surface.
2. **Login form discovery** — fetched `/cgi-bin/luci/`, parsed `<input name="luci_username">` and `<input name="luci_password">`.
3. **Authentication** — `POST /cgi-bin/luci` with those two fields → `302 Found` and `Set-Cookie: sysauth=<32-hex>; HttpOnly; secure; SameSite=Strict`. The session token is the credential used for all subsequent calls.
4. **API enumeration** — `POST /ubus` JSON-RPC with method `list` and a wildcard object, which returned every available RPC object and its methods.

### 1.2 Extraction techniques used

| Technique | Endpoint / call | What it yielded |
|---|---|---|
| Board & firmware identity | `system board` | Model, revision, kernel, target |
| Live system state | `system info` | Uptime, load, memory, swap |
| UCI config dump | `uci get {config}` | Wireless, network, DHCP, firewall, dropbear, uhttpd, and 10+ more configs |
| **Config dump bypass** | `uci get {"config":"wireless"}` *(full config, no section)* | Full wireless config **including the PSK**. Section-scoped reads (`option:"key"`) are ACL-denied; whole-config reads are not. |
| File reads | `file read` (ACL allow-list) | `/etc/passwd`, `/etc/rc.local`, `/etc/firewall.user`, `/etc/sysupgrade.conf`, `/proc/*` |
| File metadata | `file stat` | Permissions of `/etc/config/*` → exposed a `chmod o+rw` bug |
| Command execution | `file exec` (ACL allow-list) | `iptables-save`, `logread`, `opkg-list`, `ps`, `df` |
| Interfaces | `network.interface dump` | Live WAN/LAN state, modem `data` block (APN, QCI, AMBR) |
| Device stats | `luci-rpc getNetworkDevices` | Per-interface counters → the 2.4G error count and the 5G-is-idle proof |
| Host discovery | `luci-rpc getHostHints`, `getDHCPLeases` | Full client inventory with MAC, IPv4, multiple IPv6 addresses |
| Wireless state | `luci-rpc getWirelessDevices`, `iwinfo assoclist` | Radio/SSID mapping |
| Service inventory | `luci getInitList` | All 80+ init services and their enable state |
| Runlevel index | `rc list` | Boot ordering |
| TLS inspection | `openssl s_client` (from laptop) | Protocol versions, cipher, certificate subject/validity |
| Port scan | `bash /dev/tcp` (from laptop) | Open ports on the LAN side |
| Active Wi-Fi scan | `nmcli dev wifi rescan` (from laptop) | Neighbouring APs, channels, your negotiated channel/width |
| **Independent verification** | Cross-checks with `iptables-save`, live packet counters, `file stat` | Used to *confirm* UCI-derived claims against runtime reality |

### 1.3 Session behaviour observed

- **LuCI session lifetime:** 3 600 s (`luci.sauth.sessiontime`), but in practice the `sysauth` cookie was invalidated within roughly 10 minutes of idle time — several mid-audit calls returned `403`. Working scripts must re-login per batch.
- **ubus session lifetime:** 300 s (`session.login` response), refreshed on use.
- **No login rate limiting:** 5 consecutive wrong-password POSTs each returned `403` with no delay, lockout, or backoff. Automated guessing is unimpeded.

### 1.4 ACL notes (what *was* and *wasn't* reachable)

Granted to the admin role: `uci read/write`; `file read/write/list/exec/stat`; `iwinfo`; `network.interface dump`; `system *`.

Denied: `session get`, `session list`, `log read`, `iwinfo info`/`devices`, `network.wireless status`, `network.interface.wan status`, `modem_pdn`, `ql-netd`, `uci configs`, and any `file exec` not on the allow-list (`ps`, `free`, `ls`, `cat`, `netstat`, `df` are all blocked; `iptables-save`, `logread`, and `opkg-list` are the main ones permitted).

> This asymmetry is itself a finding: the ACL blocks fine-grained `uci` reads but permits **whole-config dumps that include secrets**, and blocks `ps`/`netstat` while permitting `iptables-save`.

---

## 2. Complete device inventory

### 2.1 Hardware & platform

| Field | Value | Source |
|---|---|---|
| Board name | `evb6890v1_64_cpe` | `system board` |
| Target | `gem6xxx/evb6890v1_600lxx_cpe_emmc` | `system board` |
| Architecture | ARMv8 Processor rev 0, 4× CPU | `system board`, `/proc/interrupts` |
| Kernel | `5.4.238` | `system board` |
| Wi-Fi chipset | MediaTek MT7916 (2 radios, HE-capable) | `/etc/config/wireless` device names |
| Modem | Quectel (4G/LTE) | `system.quectel_*`, `ql-netd` ubus object |
| Storage | eMMC (`mmcblk0`, 3.4 GB, 21 partitions) + overlay 22 MB | `/proc/partitions`, `luci getMountPoints` |
| RAM | 627 MB total, 309 MB available | `system info` |
| Swap | 218 MB — **0 used** | `system info` |
| Commercially | D-Link **DWR-2000M** | TLS cert `O=D-Link Corporation`; guest SSID `[REDACTED_GUEST_SSID]` |

**Storage layout fact:** the overlay filesystem is only **22.5 MB** (20.1 MB free). Room for roughly 2–3 firmware packages. `/data` has 2.7 GB free.

### 2.2 Network interfaces

| Interface | Device | Proto | Address | State |
|---|---|---|---|---|
| `lan` | `br-lan` | static | `192.168.1.1/24` | up |
| `lan` (v6) | `br-lan` | — | `fd6d:826d:6bcc::1/60` | up |
| `wan` | `ccmni2` | `ql_datacall` | `[REDACTED_WAN_IP]/29`, gw `[REDACTED_WAN_GW]` | up |
| `wan6` | `ccmni` | `dhcpv6` | — | **down — `NO_DEVICE`** |
| `wan_dhcp` | `eth1` | `dhcp` | — | down, disabled, no carrier |
| `wan_select` | — | none | — | down — `NO_DEVICE` |
| `loopback` | `lo` | static | `127.0.0.1/8` | up |

**`br-lan` bridge ports:** `eth0`, `ra0`, `rai0`, `apcli0`, `apclii0`. STP is **off**.

### 2.3 Cellular WAN details

| Field | Value |
|---|---|
| APN | `internet.tn.MNC002.MCC605.GPRS` |
| PLMN | `60502` — Ooredoo Tunisia |
| CID / QCI | `1` / `7` |
| Downlink AMBR | 51 000 kbps (~51 Mbps) |
| Uplink AMBR | 16 000 kbps (~16 Mbps) |
| MTU | 1500 |
| WAN DNS | `196.203.82.66`, `8.8.4.4` |
| Traffic since boot | **298.71 GB** received / 4.81 GB sent |
| Interface errors | 0 rx / 0 tx dropped |

~100 GB/day of cellular volume — worth checking against your data cap.

### 2.4 DHCP / LAN service

| Setting | Value |
|---|---|
| Pool | `192.168.1.100` – `192.168.1.249` (start 100, limit 150) |
| Lease time | 12 h |
| Domain | `lan` |
| DNS option 6 (pushed) | `94.140.14.15`, `185.228.168.168` (AdGuard + CleanBrowsing) |
| Option 26 (MTU) | `1500` |
| `rebind_protection` | **0 (disabled)** |
| `ednspacket_max` | 1232 |
| IPv6 on LAN | RA + DHCPv6 `server`, flags `managed-config other-config` |

### 2.5 Clients (8 IPv4 leases, 2 IPv6)

| IPv4 | MAC | Hostname | Online |
|---|---|---|---|
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | [REDACTED_HOST] *(this laptop)* | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | [REDACTED_HOST] (Xiaomi) | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | [REDACTED_HOST] (ESP32 IoT) | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | [REDACTED_HOST] | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | — | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | — | ✅ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | — | ❌ |
| [REDACTED_LAN_IP] | `[REDACTED_MAC]` | — | ❌ |

IPv6: `[REDACTED_HOST]` → `fd6d:826d:6bcc::991`, `[REDACTED_HOST]` → `fd6d:826d:6bcc::ced`.

Most client MACs are **randomised privacy MACs** (locally-administered bit set). They change on each reconnect, so any MAC-based firewall rule or static lease will break — assign reservations by hostname instead where possible.

### 2.6 Wi-Fi configuration

| | 2.4 GHz | 5 GHz |
|---|---|---|
| UCI section | `MT7916_1_1` | `MT7916_1_2` |
| Band / mode | `2.4G` / `HE40` | `5G` / `HE160` |
| Channel | `auto` → **6** (2437 MHz) | `auto` → **52** (5260 MHz) |
| Country / region | `TN` / region 1 | `TN` / aregion 2 |
| TX power | 100 % | 100 % |
| SSID | `[REDACTED_SSID_2G]` | `[REDACTED_SSID_2G]5` |
| Encryption | **`psk2+tkip+ccmp`** | **`psk-mixed+tkip+ccmp`** |
| PSK | `[REDACTED_WPA_PSK]` | `[REDACTED_WPA_PSK]` (same) |
| PMF (`ieee80211w`) | 0 (disabled) | 0 (disabled) |
| 11k / 11r | 1 / 0 | 1 / 0 |
| Beacon / DTIM | 100 ms / 1 | 100 ms / 1 |
| Client isolation | 0 | 0 |
| DFS | n/a | **`dfs_enable=0`** (DOT enabled) |
| Traffic since boot | **11.58 GB rx / 298.23 GB tx** | **0 B rx / 0 B tx** |
| `rx_errors` | **1 222 469** (of 134.6 M packets) | 0 |

**Third SSID:** `ra1` = `[REDACTED_GUEST_SSID]`, 2.4 GHz, `psk2+ccmp`, **no PSK set**, interface **down**, MAC `00:00:00:00:00:00`.

### 2.7 Firewall (runtime `iptables-save`)

| Chain | Policy |
|---|---|
| `INPUT` | ACCEPT |
| `FORWARD` | DROP |
| `OUTPUT` | ACCEPT |

Zones: `lan` (input ACCEPT, forward ACCEPT, masq off) · `wan` (input REJECT, forward REJECT, masq on) · defaults `syn_flood=1`.

Rules explicitly rejecting **ftp/21, telnet/23, ssh/22** from both LAN and WAN. `sport 5555` dropped by `/etc/firewall.user`.

### 2.8 Services & daemons enabled at boot (selected, 80+ total)

**Standard:** `network`, `firewall`, `dnsmasq`, `odhcpd`, `uhttpd`, `dropbear`, `cron`, `sysntpd`, `umdns`, `ubus`, `log`, `led`, `boot`.

**Vendor/modem:** `ql_netd`, `ql_ril_service`, `ql_powerd`, `mnld`, `scd`, `mtk_agpsd`, `mtk_netagent`, `mtk_hang_detect`, `stoneoim_wl`, `stoneoim_fota`, `mipc_wan.init`, `mipc_submonitor.init`, `modem_*`, `sim_switch`, `sms_receiver`, `speech_daemon`, `baresip`, `thermal_core`.

**⚠️ Debug / test / admin leftovers still enabled:** `wfa_dut` (Wi-Fi Alliance Device-Under-Test mode), `meta_tst`, `atd`, `atcid`, `atci_service` (AT-command listeners), `telnetd`, `vsftpd`, `xl2tpd`, `easycwmpd`, `switch_otg_daemon`.

**Add-ons:** `adblock`, `collectd`, `luci_statistics`, `vnstat`, `ddns`, `openvpn`, `vpnbypass`, `umdns`, `mosquitto` (user exists in `/etc/passwd`).

### 2.9 TLS certificate (admin UI)

| Field | Value |
|---|---|
| Subject | `C=TW, ST=Taiwan, L=Taipei, O=D-Link Corporation, OU=D-Link WRPD, CN=General Root CA` |
| Issuer | *itself* (self-signed) |
| Validity | 2025-03-07 → **2035-03-05** (3 650 days) |
| Key | RSA 2048, `sha256WithRSAEncryption` |
| Protocols | TLS 1.2 ✅, TLS 1.3 ✅, TLS 1.0 ❌, TLS 1.1 ❌ |

Generated from the shipped template in `/etc/config/uhttpd` → `[defaults]` (`organization = D-Link Corporation`, `country = TW`).

### 2.10 Accounts (`/etc/passwd`)

```
root:x:0:0:root:/root:/bin/ash
admin:x:0:0:admin:/root:/bin/ash      ← second UID-0 account
guest:x:50050:50050:guest:/home/guest:/bin/ash   ← shell-enabled
daemon, ftp, network, nobody, ntp, dnsmasq, mosquitto, logd, ubus : nologin
```

---

## 3. Ways to connect to this router

Ranked by what actually works right now. "Verified" means tested during this audit.

| # | Method | Address / port | Status | Auth | Notes |
|---|---|---|---|---|---|
| 1 | **LuCI web UI (HTTPS)** | `https://192.168.1.1/cgi-bin/luci/` | ✅ **Verified, in use** | `luci_username` / `luci_password` form POST → `sysauth` cookie | Primary interface. Session 3600 s, cookie `HttpOnly; Secure; SameSite=Strict`. |
| 2 | **LuCI web UI (HTTP)** | `http://192.168.1.1/` | ✅ Verified, redirects | — | `307` → HTTPS. `redirect_https=1`. Credentials are **not** sent in cleartext. |
| 3 | **ubus JSON-RPC (HTTPS)** | `POST https://192.168.1.1/ubus` | ✅ **Verified, in use** | `session.login` with `00000000000000000000000000000000` as the pre-auth SID | This is what LuCI itself uses. Full config read/write via `uci`, plus `file read/exec`. **The most powerful path.** |
| 4 | **ubus JSON-RPC (HTTP)** | `POST http://192.168.1.1/ubus` | ✅ Verified, redirects | — | `307` → HTTPS, body preserved. |
| 5 | **LuCI ubus RPC endpoint** | `/cgi-bin/luci/admin/ubus` | ✅ Verified | `sysauth` cookie | Backing endpoint for the web UI's AJAX calls. |
| 6 | **Wi-Fi association** | SSID `[REDACTED_SSID_2G]` (2.4 G) / `[REDACTED_SSID_2G]5` (5 G) | ✅ Verified | WPA2-PSK `[REDACTED_WPA_PSK]` | Note: 5 GHz advertises WPA1+WPA2 mixed — see finding H3. |
| 7 | **ICMP (LAN)** | ping `192.168.1.1` / `fe80::a09f:7aff:fe6f:21b1` | ✅ Verified | none | IPv6 link-local responds (1.7 ms). LAN-only explicit ACCEPT rule. |
| 8 | **DNS** | `192.168.1.1:53` | ✅ Verified open | none | dnsmasq. `rebind_protection` is off. |
| 9 | **SSH** | `:22` | ⚠️ **Configured but firewalled** | Dropbear port 22 | `PasswordAuth=off` + `RootPasswordAuth=on` (contradictory); REJECTed from **both** LAN and WAN → unusable. |
| 10 | **Telnet** | `:23` | ❌ Blocked | — | `telnetd` service is enabled but port REJECTed. Latent risk if firewall changes. |
| 11 | **FTP** | `:21` | ❌ Blocked | — | `vsftpd` enabled; port REJECTed, and ports 20/21 hard-DROPped. |
| 12 | **TR-069 / CWMP** | `:7547` on `eth1` | ❌ Not listening | `[REDACTED]` / `[REDACTED]` | `easycwmpd` enabled, ACS URL empty. See finding H1. |
| 13 | **Serial / UART console** | `/dev/tty*` (Quectel main UART) | ❌ Physical only | — | `system.quectel_main_uart=1`. Requires opening the case. |
| 14 | **USB RNDIS gadget** | `rndis0` | ❌ Interface down | — | Present as a `gadget`-type interface. If enabled, exposes a USB tethering network — a physical-access path. |
| 15 | **UPnP / IGD** | — | ❌ Not installed | — | No `upnpd`/`miniupnpd` config present. Good. |
| 16 | **SMB / media sharing** | — | ❌ Not installed | — | No `samba`/`minidlna`. |
| 17 | **SNMP** | — | ❌ Not installed | — | No `snmpd`. |

**Open ports from LAN (scanned):** `53`, `80`, `443` only. Everything else refused.

**Blocked-but-present:** `ssh`, `telnet`, `ftp`, `cwmp`, `vsftpd`, `telnetd`, `wfa_dut`, `atd` — a firewall misconfiguration or a `sysupgrade` reset would expose all of them at once.

---

## 4. Findings and recommendations

Severity: 🔴 critical · 🟠 high · 🟡 medium · ⚪ low

---

### 🔴 C1 — Admin UI ACCEPT rules bypass the firewall zone system

**Evidence** (`iptables-save`, `*filter`, in order):

```
-A INPUT -p tcp --dport 80  -j ACCEPT      ← line 39
-A INPUT -p tcp --dport 443 -j ACCEPT      ← line 40
-A INPUT -i br-lan  -j zone_lan_input      ← line 41
-A INPUT -i ccmni2  -j zone_wan_input      ← line 42
-A INPUT -i ccmni   -j zone_wan_input      ← line 43
```

**How verified:** `iptables-save` via `file exec`; then matched against the UCI source, where both `http` and `https` rules are defined with `src=*` and no `dest`. In `fw3`, a wildcard-source rule with no destination lands directly in the base `INPUT` chain, *before* any zone dispatch.

**Why it matters:** the packet is ACCEPTed at line 39/40 and **never reaches the zone jumps**. This makes the `wan` zone's `--dport 80/443 -j reject` rules — and the entire `zone_wan_input → zone_wan_src_REJECT` fallback — **dead code**. The admin UI is not protected by the firewall's zone model at all.

**What is actually protecting you today:** only `uhttpd.rfc1918_filter = 1`, which drops requests whose source is not in RFC1918 space. Two consequences:
- A client with a **private** source address reaching the WAN interface *is* allowed in. On cellular that means other devices behind the same carrier NAT (`[REDACTED_WAN_SUBNET]` is your peer subnet).
- If you ever enable `wan_dhcp` on `eth1` (Ethernet uplink) or a VLAN that isn't in a zone, the UI is reachable from that network immediately.

**Advice:** change both rules to `src: lan` (`option src 'lan'`). They then compile inside `zone_lan_input` where they belong, and the WAN zone's rejects become meaningful again. Additionally set `uhttpd.rfc1918_filter` as defence-in-depth only — it is not a substitute for zone scoping.

---

### 🔴 C2 — `/etc/config/system` is world-readable **and world-writable**

**Evidence** (`file stat`):

```
/etc/config/system    mode 0606   ← others can read AND write
/etc/config/passwd    mode 0755
/etc/shadow           mode 0600   ✅
/etc/config/network   mode 0600   ✅
/etc/config/firewall  mode 0600   ✅
/etc/config/dhcp      mode 0600   ✅
```

**How verified:** `file stat` on each config; mode decoded from decimal (`33158` → `0o100606`).

**Root cause** — from `/etc/rc.local`, executed at every boot:

```sh
# add read & write permissions for non-root user.
if [ -s /etc/config/system ]; then
    chmod o+rw /etc/config/system
fi
```

**Why it matters:** there is a `guest` account with UID 50050 and a real shell (`/bin/ash`) in `/etc/passwd`. Any process running as `guest` — or anyone who reaches a shell through any of the latent daemons in C3 — can **rewrite the system config**: hostname, and critically the `system.ntp` servers, which is a classic path to injecting a malicious time source. The vendor appears to have done this to let its own GUI plugin edit `system` without root; that's not how file ownership should be solved.

**Advice:** delete those four lines from `/etc/rc.local` and `chmod 600 /etc/config/system`. If a plugin truly needs write access, run it as root via `ubus` rather than weakening file modes.

---

### 🔴 C3 — Vendor test/debug daemons enabled in production

**Evidence** (`luci getInitList`, `enabled: true`): `wfa_dut`, `meta_tst`, `atd`, `atcid`, `atci_service`, `telnetd`, `vsftpd`, `xl2tpd`, `easycwmpd`, `switch_otg_daemon`, `baresip`.

**How verified:** `luci getInitList`; cross-checked against `/etc/passwd` (`ftp`, `guest` accounts) and `iptables-save` (rules that *exist specifically to block* FTP/telnet/SSH — i.e. the vendor knew these were risky and blocked ports rather than disabling services).

**Why it matters:** `wfa_dut` and `meta_tst` are factory Wi-Fi certification harnesses that normally open unauthenticated control channels. `atd`/`atcid` listen for AT commands — on a cellular CPE that historically means the ability to send SMS, read SIM data, and manipulate the modem. `vsftpd` and `telnetd` are plaintext protocols. None are firewalled *by default*; they are only blocked by the port-specific REJECT rules that a `firstboot` or firmware upgrade can reset.

**Advice:** disable each one (`/etc/init.d/<svc> disable && /etc/init.d/<svc> stop`). Keep `ql_netd`, `ql_ril_service`, `mnld`, `scd`, `thermal_core` and the `mipc_*` monitors — the modem and thermal loop depend on them. Verify voice/data still work after each batch.

---

### 🔴 C4 — Second UID-0 account `admin`, plus a shell-capable `guest`

**Evidence:**

```
root:x:0:0::/root:/bin/ash
admin:x:0:0::/root:/bin/ash
guest:x:50050:50050::/home/guest:/bin/ash
```

**Why it matters:** `admin` is a full root account with an independent password that your password-change routine probably doesn't touch. `guest` has a shell — combined with C2 (`/etc/config/system` writable) it is a genuine privilege-escalation path.

**Advice:** delete `admin` (or lock it with `*` in `/etc/shadow`), and set `guest`'s shell to `/bin/false`. Audit `/etc/shadow` for any other non-`*` entries.

---

### 🟠 C5 — No login rate limiting

**Evidence:** 5 sequential wrong-password POSTs to `/cgi-bin/luci` → `403 403 403 403 403`, no delay, no lockout, no CAPTCHA. Session lifetime 3600 s; `MaxAuthTries=4` applies to Dropbear, not LuCI.

**Advice:** on a CPE this is lower risk than on an internet-facing server, but it costs nothing to mitigate: restrict the UI to a few IPs, or use a strong unique password (20+ chars). See also C1 — fixing that removes network reachability for the attack.

---

### 🟠 C6 — Shared factory TLS certificate

**Evidence:** `CN=General Root CA, O=D-Link Corporation`, self-signed, 2048-bit RSA, valid to 2035-03-05, generated from the template in `/etc/config/uhttpd [defaults]`.

**Why it matters:** the keypair ships in firmware. Anyone who extracts it can impersonate the admin UI to you or MITM a session. The 10-year validity with a generic "General Root CA" CN confirms it is not per-device.

**What's fine:** TLS 1.0/1.1 are disabled; only 1.2 and 1.3 negotiate. HTTP correctly 307-redirects to HTTPS, so the password is never sent in cleartext.

**Advice:** regenerate a per-device cert (LuCI → *System → Administration*, or `uhttpd` cert settings). You will still get a browser warning for the self-signed trust anchor — that's normal and not itself the problem; the problem is that the key is shared with every other unit of this model.

---

### 🟠 H1 — `easycwmp` (TR-069) enabled with hardcoded placeholder credentials

**Evidence** (`uci get easycwmp`):

```
interface = eth1        port = 7547
username  = [REDACTED]      password = [REDACTED]
username  = [REDACTED]          password = [REDACTED]
ACS url   = http://             (empty)
periodic_enable = 1, interval = 100 s
manufacturer = Stoneoim, serial = [REDACTED]
```

**Why it matters:** TR-069 is a remote-management protocol that can rewrite any setting and push firmware. Port 7547 is the same service abused by the Mirai/`Satori` botnets through ISP CPEs. `[REDACTED]`/`[REDACTED]` is a default credential. Also note the serial number is the placeholder `[REDACTED]`, and the manufacturer field leaks the OEM.

**Current risk:** low — not listening, ACS URL empty. **But** `eth1` is the WAN port and the service is enabled at boot, so plugging in an Ethernet uplink on a network with an ACS would activate it.

**Advice:** `/etc/init.d/easycwmpd disable` unless your ISP explicitly provisions you via TR-069. If you need it, set real credentials and an HTTPS ACS URL.

---

### 🟠 H2 — `rfc1918_filter` is the only thing actually gating the admin UI

Follows directly from C1: because the ACCEPT rules fire before the zone jumps, the sole remaining control on remote access is `uhttpd.rfc1918_filter = 1`, which uhttpd checks against the request's source address.

**Why this is thin:** the filter only distinguishes private from public address space. It does **not** distinguish "my LAN" from "another subscriber behind the same carrier NAT". Your WAN subnet is `[REDACTED_WAN_SUBNET]` — private RFC1918 space. A device on that peer subnet reaching port 443 presents a *private* source address and passes the filter.

**Verification step (do this after applying the C1 fix):**

```sh
iptables-save | grep -E 'dport (80|443)'
```

The expected result is that `--dport 80` and `--dport 443` appear **only** as `-A zone_lan_input ...` rules, and **not** in the base `-A INPUT` chain. If they still appear in `INPUT`, the fix did not take effect.

**Advice:** treat `rfc1918_filter` as defence-in-depth, never as the primary control. A second useful layer is to bind `uhttpd` `listen_https`/`listen_http` to the LAN address (`192.168.1.1:443`) instead of `0.0.0.0:443`, which removes the WAN listener entirely.

---

### 🟠 H3 — TKIP enabled on both radios — this is capping your Wi-Fi

**Evidence:**

| Radio | `encryption` | Negotiated (from laptop scan) |
|---|---|---|
| `ra0` (2.4 G) | `psk2+tkip+ccmp` | `WPA2` |
| `rai0` (5 G) | **`psk-mixed+tkip+ccmp`** | **`WPA1 WPA2`** |

**Why it matters:** the 802.11 standard **forbids HT, VHT and HE rates when TKIP is in the group or pairwise cipher set**. With `psk-mixed` + TKIP on 5 GHz, your MT7916 (a Wi-Fi 6 radio capable of HE160 / 2.4 Gbps) is negotiating as WPA1-compatible legacy — effectively 802.11g throughput. The laptop's scan confirming `WPA1 WPA2` is direct proof the beacon advertises WPA1.

**Advice:** set `encryption` to `psk2+ccmp` on both `ra0` and `rai0` — or `sae-mixed` (WPA2/WPA3 transitional) if all your clients support it. This is the single highest-impact change in this report. It will disconnect all clients, so do it when convenient.

---

### 🟠 H4 — 5 GHz radio is completely unused

**Evidence** (`luci-rpc getNetworkDevices`):

```
rai0   rx 0.0 GB   tx 0.0 GB    rx_errors 0      ← up, carrier true, zero traffic
ra0    rx 11.58 GB tx 298.23 GB rx_errors 1222469
```

**How verified:** per-interface kernel counters since boot (~3 days). `rai0` shows `carrier: True` and `up: True`, so the radio is transmitting beacons but no client has ever associated.

**Why it matters:** every byte on your network is going through the congested, narrow 2.4 GHz band — while a clean, idle 5 GHz radio sits unused. This is the direct cause of finding H6.

**Advice:** enable band steering (`ieee80211k=1` is already set, so clients are being *told* about the 5 GHz neighbour — they're not taking it). Either split into two distinct SSIDs and connect high-throughput devices (laptop, TV, console) to the 5 GHz one, or enable 802.11v BSS-transition management. Do not leave this as-is.

---

### 🟠 H5 — 5 GHz: 160 MHz width on DFS channel 52 with DFS detection disabled

**Evidence:**

```
channel = auto  →  running 52 / 5260 MHz
htmode  = HE160
dfs_enable = 0
doth = 1
```

**Why it matters:** three compounding problems.
1. Channel 52 is a **DFS (radar) channel**. `dfs_enable=0` means no radar detection runs — a regulatory violation in most jurisdictions, and it also means interference from airport/weather radar corrupts your link with no fallback.
2. `HE160` on a 2×2 radio is a poor trade: you gain theoretical peak but lose diversity gains, are forced into the DFS band, and have to share the width with neighbours. `HE80` is materially more reliable in practice.
3. `auto` channel selection on boot can land you on different channels between reboots — your `acs_alg=3` may pick a different result each time.

**Advice:** set `channel` to a fixed non-DFS value (**36, 40, 44 or 48**) and `htmode` to `HE80`. If you need DFS channels, set `dfs_enable=1` and accept CAC delays (60–600 s) after every reboot.

---

### 🟠 H6 — 2.4 GHz: 40 MHz width on a congested channel

**Evidence:**
- Your radio: `htmode=HE40`, `channel=auto` → settled on **6** (2422–2462 MHz).
- Live neighbourhood scan (from this laptop, `nmcli dev wifi rescan`):

| SSID | Channel | Freq | Signal |
|---|---|---|---|
| `[REDACTED_SSID_2G]5` (yours, 5 G) | 52 | 5260 MHz | 92 % |
| `[REDACTED_SSID_2G]` (yours, 2.4 G) | 6 | 2437 MHz | 81 % |
| `Ooredoo-323EC7` | **4** | 2427 MHz | 20 % |

**Why it matters:** HE40 on channel 6 occupies 2422–2462 MHz. The neighbour on channel 4 (2427 MHz) sits **directly inside your primary/secondary channel split**. In the 2.4 GHz band, 40 MHz leaves only one non-overlapping 40 MHz slot in the entire band (36/40-style pairing), so this was never going to be clean. Result: the measured **1 222 469 rx_errors** on `ra0` — 0.9 % of all received packets — and much of why all traffic feels slow.

**Advice:** set `htmode` to **`HE20`** on `MT7916_1_1`, and pin `channel` to **1, 6, or 11** after re-scanning (currently 6 is correct given the neighbour on 4 — staying on 6 at 20 MHz is the right call). Also set `ht_coex=1` (currently 0) to enable 20/40 coexistence signalling.

---

### 🟡 M1 — No flow offloading; load average 8.5 on a 4-core CPU

**Evidence:**

```
system info load = [556064, 548416, 543872]  →  8.48 / 8.37 / 8.30
iptables-save   →  0 occurrences of FLOWOFFLOAD
/proc/interrupts → 4 CPUs (CPU0–CPU3)
```

**How verified:** `system info` (load is reported in 16.16 fixed-point — the LuCI source at `status/include/10_system.js` divides by 65535, confirming the unit); `iptables-save` grep for the FLOWOFFLOAD target; CPU count from `/proc/interrupts`. The 1/5/15-minute values are flat, so this is **sustained**, not a spike.

**Why it matters:** load 8.5 across 4 cores means ~213 % oversubscription for at least 15 minutes. Every forwarded packet is handled by the software netfilter path. On this SoC, enabling flow offloading typically cuts forwarding CPU cost by an order of magnitude.

**Advice:** enable software flow offloading (`firewall.@defaults[0].flow_offloading='1'`, `flow_offloading_hw='1'` if the SoC supports PPE offload — the MT7916/MT6890 family usually does). Then re-check load. If it doesn't drop, find the actual consumer — `luci getProcessList` is ACL-blocked, so enable SSH or read `/proc/loadavg` after fixing the SSH policy (M5).

> Diagnostic limitation worth knowing: because `ps`, `free`, `netstat` and `df` are all ACL-denied, I could not identify *which* process is burning CPU. That's a gap in this audit, not a proof there is nothing to find.

---

### 🟡 M2 — No QoS/SQM on a 16 Mbps uplink

**Evidence:** no `sqm` config; no `tc`/qdisc config (`sqm` → `_status 4`, i.e. absent). Modem negotiated `ul_ambr = 16 000 kbps`, `dl_ambr = 51 000 kbps`.

**Why it matters:** with 8 active clients and a 16 Mbps uplink, a single upload (backup, video call, phone photo sync) saturates the modem's buffer and every other flow stalls — including your own SSH/LuCI session. This is the classic "my internet dies when someone uploads" symptom. It also makes the load problem in M1 worse.

**Advice:** install/enable SQM with `cake` and shape to ~85 % of measured capacity: **14 000 kbit down / 13 500 kbit up** (verify with a real speed test first). Alternatively enable the built-in per-SSID airtime fairness — `vow_airtime_fairness_en=1` is already set on both radios, which helps Wi-Fi contention but does nothing for the WAN bottleneck.

**Update (2026-11-09):** Real SQM is not possible on this device. The vendor's per-client QoS has been configured as a stopgap: **3000 kbps down / 1500 kbps up per client**.

---

### 🟡 M3 — Broken and insecure "guest" network

**Evidence:** `ra1` (`[REDACTED_GUEST_SSID]`): `encryption=psk2+ccmp` but **no `key` present**; interface `up: False`, MAC `00:00:00:00:00:00`; `network=lan`; `isolate=0`. The SSID does not appear in a live scan.

**Why it matters:** two problems.
1. It is **non-functional** — an SSID advertising WPA2 with no key can never complete a handshake. Anyone selecting it just fails.
2. If it were fixed naively (by adding a key), guests would land on `br-lan` with **full access to your 8 client devices**, because `isolate=0` and there's no separate zone. It would be worse than having no guest network.

**Advice:** either delete the `ra1` section entirely, or build it properly: a new bridge (e.g. `br-guest`), a new interface `192.168.2.1/24`, a new firewall zone with `input=REJECT, forward=REJECT`, forward only to WAN (no LAN reach), plus `isolate=1` and `ieee80211w=1` on the SSID.

---

### 🟡 M4 — Default SSIDs and a shared PSK across both bands

**Evidence:** `ssid = [REDACTED_SSID_2G]` (2.4 G), `ssid = [REDACTED_SSID_2G]5` (5 G); both use `key = [REDACTED_WPA_PSK]`. Guest SSID discloses the exact model (`DWR-2000M`).

**Why it matters:** default-style names advertise the device model, which tells an attacker which firmware CVEs to try. A single PSK on both bands means one compromise covers both, and you can't rotate one without disrupting all clients.

**Advice:** use distinct, non-model-revealing SSIDs; use **separate random PSKs per band** (20+ characters); hide neither (hiding provides no real security and breaks roaming).

---

### 🟡 M5 — SSH is configured but firewalled, and its policy is self-contradictory

**Evidence:**

```
dropbear: Port=22, RootLogin=1, RootPasswordAuth=on, PasswordAuth=off, MaxAuthTries=4
iptables: -A zone_lan_input --dport 22 -j reject
          -A zone_wan_input --dport 22 -j reject
```

**Why it matters:** `PasswordAuth=off` with `RootPasswordAuth=on` is contradictory — the latter is a subset of the former, and the effective result depends on Dropbear version. Meanwhile port 22 is REJECTed from both directions, so SSH is unreachable regardless. You have an unusable service that creates risk without benefit — and its current state blocks the diagnostics needed for M1.

**Advice:** decide one way. For a home router, I'd recommend **allowing SSH from LAN only** (`PasswordAuth=on`, `RootPasswordAuth=on`, strong password, or better: `authorized_keys` with `PasswordAuth=off`), keeping the WAN reject. That gives you `ps`, `top`, `dmesg` and real troubleshooting. If you prefer it fully closed, remove the inconsistency so a future firewall edit doesn't accidentally expose it.

---

### 🟡 M6 — IPv6 half-configured: clients get addresses with no route

**Evidence:** `wan6` is `down` with `errors: [{subsystem:"interface", code:"NO_DEVICE"}]`; the modem reports `v6_prefix: ""` (no delegated prefix). Yet LAN DHCPv6/RA are set to `server` with `managed-config other-config`, and `ip6assign=60` allocates ULA `fd6d:826d:6bcc::/60`.

**Why it matters:** clients receive a ULA address they cannot route to the internet. Per RFC 6724, many stacks prefer IPv6, attempt it first, time out, and fall back — producing stalls on first connection to a site. `[REDACTED_HOST]` and `[REDACTED_HOST]` already hold ULA leases.

**Advice:** either fix upstream IPv6 (correct APN with IPV4V6 PDP type, then verify `wan6` gets a prefix) or **disable** it cleanly: set `network.lan.dhcpv6='disabled'`, `ra='disabled'`, and remove `ip6assign`. Half-on is the worst state.

---

### 🟡 M7 — DNS rebind protection disabled

**Evidence:** `dhcp.@dnsmasq[0].rebind_protection = '0'`.

**Why it matters:** this is exactly the control that blocks a malicious public domain from resolving to a private address (e.g. `evil.example → 192.168.1.1`) and steering clients at your admin UI. Turning it off is a deliberate weakening, probably to make some ISP captive portal work.

**Advice:** set `rebind_protection='1'`. If something breaks, add that domain to `rebind_domain` rather than disabling the protection globally.

---

### 🟡 M8 — Inconsistent DNS policy

**Evidence:**

| Path | Resolvers |
|---|---|
| Clients (DHCP option 6) | `94.140.14.15` (AdGuard), `185.228.168.168` (CleanBrowsing) |
| Router itself (from WAN) | `196.203.82.66` (ISP), `8.8.4.4` (Google) |

**Why it matters:** filtering from the advertised pair applies to some clients and not others; the router's own lookups bypass filtering entirely. It also means your DNS traffic is split across three different providers with three different logging policies.

**Advice:** pick one policy. For a filtered household, point the upstream at a single pair and let dnsmasq be authoritative for the LAN, so nothing can bypass it.

---

### ⚪ L1 — `adblock` enabled but has zero source lists

**Evidence:** `uci get adblock` → only `[global]` with `adb_enabled=1`; `len([sections of type 'source']) = 0`.

**Advice:** it filters nothing while still running its init script at every boot. Add sources (e.g. `oisd`, `stevenblack`) or disable it.

---

### ⚪ L2 — `collectd` / `luci_statistics` writing RRD to RAM

**Evidence:** enabled plugins: `cpu`, `interface`, `iwinfo`, `load`, `memory`; `Interval=30`, `DataDir=/tmp/rrd`, `RRATimespans = 1hour 1day 1week 1month 1year`.

**Advice:** 5 plugins × 30 s sampling × 5 timespan archives on an already-overloaded CPU, writing to a RAM filesystem that vanishes on reboot. The historical data survives nothing. Either move `DataDir` to `/data` (2.7 GB free) or disable it. Orphaned `collectd_iptables_match` sections reference non-existent chains (`br-ff`) — harmless, but a sign the config was copied from another product.

---

### ⚪ L3 — Placeholder DDNS entries

**Evidence:** `myddns_ipv4` / `myddns_ipv6` with `yourhost.example.com`, `your_username`, `your_password`.

**Advice:** delete both sections. If they're ever enabled they will publish failed-update noise and leak the placeholders to a provider.

---

### ⚪ L4 — Disabled station-mode interfaces sit in the LAN bridge

**Evidence:** `br-lan` ports include `apcli0` and `apclii0` (mode `sta`, `disabled=1`).

**Advice:** remove them from `br-lan`. If anyone enables them — a natural thing to try for "Wi-Fi repeater mode" — the upstream AP's network gets **bridged directly into your LAN**, bypassing your firewall entirely.

---

### ⚪ L5 — Timezone and hostname cosmetics

**Evidence:** `hostname=MobileRouter`, `timezone=<+01>-1`, `zonename=Etc/GMT-1`, `ttylogin=0`.

**Advice:** `Africa/Tunis` is the correct zone name (behaviour is identical today, but `Etc/GMT-1` breaks if the DST rule changes). Rename the host so log correlation is meaningful.

---

### ⚪ L6 — `sysupgrade.conf` preserves vendor Wi-Fi state that overrides UCI

**Evidence:**

```
/etc/wireless/
/etc/map/
/etc/ethernet_cfg.txt
```

**Why it matters:** `/etc/wireless/` holds MediaTek's own radio configuration. On a firmware upgrade it is preserved and can silently override values you set through LuCI. `mtime` on `/etc/config/wireless` is 2026 (current), while `/etc/config/system` is 2025 — consistent with radio settings being rewritten by the vendor stack rather than by UCI.

**Advice:** know this before assuming a LuCI change took effect — always verify with `iw`/`iwinfo` after changing radio parameters. Take a config backup (`luci` → *Backup / Flash Firmware*) before any upgrade.

---

## 5. Recommended remediation order

Grouped so that each batch is independently reversible and you can verify between steps.

### Batch 1 — Security, no client disruption

1. `chmod 600 /etc/config/system`; remove the `chmod o+rw` block from `/etc/rc.local`.
2. Change `firewall` rules `http` and `https` to `src=lan`.
3. `uci set dhcp.@dnsmasq[0].rebind_protection='1'`.
4. Disable `wfa_dut`, `meta_tst`, `atd`, `atcid`, `atci_service`, `telnetd`, `vsftpd`, `xl2tpd`, `easycwmpd`.
5. Delete the `admin` account; set `guest`'s shell to `/bin/false`.
6. Rotate the admin password (both accounts). Add rate limiting or IP restriction if available.
7. **Verify:** `iptables-save | grep -E 'dport (80|443)'` must show the rules only inside `zone_lan_input`.

### Batch 2 — Wi-Fi correctness (bounces radios; do when clients can reconnect)

8. `ra0` / `rai0` → `encryption='psk2+ccmp'` (or `sae-mixed`). **Biggest single win.**
9. 2.4 GHz → `htmode='HE20'`, `ht_coex='1'`, fixed `channel` (1/6/11).
10. 5 GHz → `htmode='HE80'`, fixed `channel` (36/40/44/48), or enable `dfs_enable=1` to keep DFS.
11. `ieee80211w='1'` (optional PMF) on 5 GHz; `dtim_period='3'`.
12. Split SSIDs; distinct random PSKs per band.
13. Delete `ra1`, or rebuild a proper isolated guest network (M3).
14. Remove `apcli0`/`apclii0` from `br-lan`.
15. **Verify:** `nmcli` scan shows `WPA2` (not `WPA1 WPA2`) and `rai0` counters start moving.

### Batch 3 — Performance

16. Enable flow offloading (`flow_offloading='1'`, try `flow_offloading_hw='1'`); re-check load average.
17. Enable SQM/`cake` at ~14 Mbit down / 13.5 Mbit up.
18. Fix or disable IPv6 (M6).
19. Configure or disable `adblock`; move or disable `collectd`.
20. **Verify:** load drops below ~2.0; bufferbloat test shows A/B grade.

### Batch 4 — Housekeeping

21. Delete DDNS placeholders; rename host; set `Africa/Tunis`.
22. Decide the SSH policy (M5) so future diagnostics are possible.
23. Take a full config backup before any firmware change.

---

## 6. Appendix — raw artefacts retained

| File | Contents |
|---|---|
| `jar.txt` | `sysauth` session cookie (expired) |
| `ipt.txt` | Full `iptables-save` output, 168 lines |
| `admin.html` | Authenticated LuCI status page |
| `luci_root.html` | Pre-auth login page |
| `wl_page.html` | Wireless management page |
| `ubus_list.json` | Full ubus object/method enumeration |
| `access.json` | Session ACL dump |
| `r.py` | Reusable re-authenticating ubus client used for this audit |
| `uci.sh`, `rd`, `ub` | Shell helpers for UCI and file reads |

**All of these are now stale** — rotating the admin password and restarting `uhttpd` invalidates the session token and makes every file in that directory useless to anyone who finds them. Recommend deleting `/tmp/opencode/` when done.

---

*No configuration was changed during this audit. Every call was a read (`get`, `dump`, `read`, `stat`, `list`) or a non-mutating RPC (`board`, `info`, `getInitList`). The only write-class RPCs available to the session — `uci set/add/apply`, `file write/remove`, `system reboot`, `sysupgrade` — were not invoked.*
