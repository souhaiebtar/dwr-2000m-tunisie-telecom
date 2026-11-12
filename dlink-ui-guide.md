# DWR-2000M — Vendor UI Guide (corrected)

**Firmware:** `1.07ME/TT` · model `DWR-2000M` · serial `[REDACTED_SERIAL]`
**Branded for:** Tunisie Telecom (TN) — custom LuCI, **not** stock OpenWrt LuCI
**Verified:** 2026-11-09, by reading the live UI's own JavaScript and endpoints

---

## ⚠️ Read this first — three corrections to the earlier audit

You were right that the UI is customised. That invalidates three things I told you, and it changes **how** several fixes must be done. Correcting them before anything else.

| # | What I said | The truth (verified) |
|---|---|---|
| 1 | "Network → Firewall → Traffic Rules" | **Does not exist.** There is no rules editor at all. The port-access matrix is **Network → Remote Management** (More page). |
| 2 | "Telnet service is enabled but firewalled" | **Wrong.** `telnet_switch = 0` — it is genuinely off. My earlier claim came from `getInitList` showing the *init script* enabled; the vendor keeps its own switch layer on top. Same for SSH: `ssh_switch = off`. |
| 3 | "5 GHz is `psk-mixed+tkip+ccmp` — TKIP enabled" | **Imprecise.** The UI value is `WPAPSKWPA2PSK` = *WPA-PSK/WPA2-PSK* mixed mode. TKIP appears in the UCI `encryption` string but the vendor UI never lets you select a cipher. The **mixed WPA1+WPA2 mode is still the problem** (a live scan confirms `[REDACTED_SSID_2G]5` beacons as `WPA1 WPA2`) — but the fix is "choose WPA2-PSK", not "disable TKIP". |

Also new and good: there is a proper **Guest** network page with a supported path to enable it, and a **Remote Management** page that is the vendor's intended control for everything I flagged in finding C1.

---

## 1. Actual menu tree

The UI has **7 top-level pages** (not the ~40 sections stock LuCI has):

```
Status ── Home · Internet · Wizard · Clients
My Wi-Fi ── Basic Settings · Advanced · Access Control · WPS · Scheduled · Guest · Relay · Site Survey · Mesh
Mobile   ── (APN, SIM, USSD, SMS, VoLTE, data traffic)
More
 ├─ Router      ── Basic information · System information · Online upgrade
 ├─ Parental Control
 ├─ Network     ── DHCP · DDNS · Port Forward · DMZ · IPv6 · QOS · VPN · Remote Management
 ├─ System      ── Password · Network Time · Lock SIM · Backup/Reset · System logs · TR069 · TR369 · Service
 ├─ Service     ── Firewall(×) · MAC filtering · IP filtering · Url filtering · Advanced
 ├─ Developer   ── Bands Lock · Cell Lock · Diagnostics
 └─ (Reboot, Language, Log out)
```

Note: **`Service → Firewall` does not load** — the page calls `admin/status/firewallAdvanced_get`, and that endpoint returns only `{"status":0,"antiDdos":"1"}` with no `pingWan` key, so the handler never populates. Treat that page as dead.

---

## 2. Fix-by-fix: where each recommendation actually lives

### ✅ Doable in the UI

| Finding | Exact path | What to do |
|---|---|---|
| **C6 / password** | More → System → **Password** | Change it. Enter current password, then new twice. |
| **H3 / TKIP-mixed** | My Wi-Fi → **Basic Settings** → 5 GHz Wi-Fi → Security | Set **`WPA2-PSK`** (currently `WPA-PSK/WPA2-PSK`). Same for 2.4 GHz. ⚠️ Drops all clients. |
| **H6 / 2.4 GHz width** | My Wi-Fi → **Advanced** → 2.4 GHz Wi-Fi → Band width | Set **`20 MHz`** (currently `40 MHz`). |
| **H5 / 5 GHz width** | My Wi-Fi → **Advanced** → 5 GHz Wi-Fi → Band width | Set **`80 MHz`** (currently `160 MHz`). |
| **H5 / channel** | My Wi-Fi → **Advanced** → Channel | Pin `5G` to **36/40/44/48** (avoid DFS 52). 2.4 GHz → keep **6** or set 1/11. |
| **H4 / 5 GHz unused** | My Wi-Fi → **Basic Settings** → *Dual-Band Ai Connect* | Currently **off**. Turn it **on** to merge both bands, or keep off and connect devices to `[REDACTED_SSID_2G]5` manually. |
| **M3 / guest network** | My Wi-Fi → **Guest** | Currently **disabled** (`enable_guest=0`), and `psd_guest` is empty. Enable it and **set a password** — the vendor will build the isolated AP for you. This is far better than editing UCI. |
| **M4 / SSIDs** | My Wi-Fi → **Basic Settings** → Name | Rename from `[REDACTED_SSID_2G]` / `[REDACTED_SSID_2G]5`. Set **different** passwords per band. |
| **WPS** | My Wi-Fi → **WPS** | Already **off** (`wps_enable=0`). Keep it off. |
| **M2 / QoS** | More → Network → **QOS** | QoS reports `on` but `limitList` is **empty** — it shapes nothing. Add a rule at ~14 Mbit down / 13.5 Mbit up. |
| **M6 / IPv6** | More → Network → **IPv6** | Reports `enabled: on`. Turn **off** — `wan6` is dead (`NO_DEVICE`) so clients get ULA addresses with no route. |
| **M1 / flow offloading** | ❌ **No UI** | Needs shell or ubus. |
| **M7 / rebind protection** | ❌ **No UI** | Needs shell or ubus. |
| **C1 / wildcard firewall rules** | ⚠️ **Partly** — see §3 | Mitigate via Remote Management checkboxes. |

### ❌ No UI at all in this build

I grepped all 7 pages for these strings; zero hits:

| Setting | Finding | Status |
|---|---|---|
| `rebind_protection` | M7 | absent |
| `flow_offloading` | M1 | absent |
| `ieee80211w` / PMF | H11 | absent |
| `isolate` (client isolation) | M3 | absent |
| `dtim_period` | L5 | absent |
| DFS enable/disable | H5 | absent |

These six require the shell or ubus. They are the reason "just use the web UI" is not a complete answer.

---

## 3. The one that matters most: Remote Management

**More → Network → Remote Management**

This page is the vendor's real port-access control. Under the hood it writes both a wildcard ACCEPT and zone-specific rules — which is exactly the bug in finding C1.

Header text: *"Tick checkboxes to enable the ports you need. And grey checkbox means it is unchangeable."*

**Current live state** (`admin/more/remote_get`), each value is `LAN` + `WAN`:

| Service | LAN | WAN | |
|---|---|---|---|
| FTP | `0` | `0` | off both — good |
| Telnet | `0` | `0` | off both — good |
| SSH | `0` | `0` | off both — this is why port 22 refused |
| Ping | `1` | `0` | LAN only — good |
| HTTP | `1` | `0` | LAN only, **greyed out — cannot change** |
| HTTPS | `1` | `0` | LAN only — good |

So your WAN exposure is already disabled at the vendor layer. **Keep HTTPS WAN and HTTP WAN unchecked** — that is your primary protection and it is working.

**What the UI cannot fix:** the wildcard `-A INPUT --dport 80/443 -j ACCEPT` rules. Those bypass the firewall zone chain entirely, so the `https_wan REJECT` rule beneath them is dead code. What actually stops a remote request is uhttpd's `rfc1918_filter`, which only tests *private vs public* source address — and your cellular peer subnet `[REDACTED_WAN_SUBNET]` **is** private.

Practical consequence: a device on your carrier's local subnet could reach the login page. Closing it fully needs one of the methods in §4.

---

## 4. Three ways to reach the settings the UI hides

### 4a. Enable the vendor SSH switch (supported, cleanest)

More → System → **Service** → **SSH Switch** → enable → Save.

This flips `ssh_switch` from `off` to `on`, which starts Dropbear. Paired with Remote Management → SSH → **LAN** ticked, you get a real shell where plain `uci` works exactly as I wrote it originally:

```sh
uci set dhcp.@dnsmasq[0].rebind_protection='1'
uci set firewall.@defaults[0].flow_offloading='1'
uci commit dhcp; uci commit firewall
/etc/init.d/dnsmasq restart; /etc/init.d/firewall reload
```

⚠️ Two cautions before you do this:
- Dropbear is configured `PasswordAuth=off` + `RootPasswordAuth=on`. That combination is contradictory and may reject your password. Test while you still have the web UI open.
- Enabling SSH also enables port 22 for anything that can reach the LAN. Leave the **WAN** box unchecked.

### 4b. Vendor JSON endpoints (no shell, works today)

Every page is a thin wrapper over plain GETs. You can call them with the `sysauth` cookie. Useful ones:

| Endpoint | Purpose |
|---|---|
| `admin/more/remote_set?remoteList={...}` | Set the port matrix directly |
| `admin/more/ssh_switch?ssh_switch=on` | Enable SSH |
| `admin/more/telnet_switch?telnet_switch=1` | Enable telnet (don't) |
| `admin/wifi/basic_set` / `advanced_set` | Radio settings |
| `admin/wifi/guest_set` | Guest network |
| `admin/status/password_set` | Change password |
| `admin/status/tr069_set` | Disable TR-069 |

The `remoteList` payload format, taken from the page source:

```json
{"ftp":"00","telnet":"00","ssh":"10","Allow-Ping":"10","http":"10","https":"10"}
```

Each value is `LAN` digit + `WAN` digit.

### 4c. ubus directly (what `batch-a.py` does)

Unchanged from before — the `uci` object accepts `set`/`apply` with a `values` object. This is the only route that reaches `rebind_protection` and `flow_offloading` **without** enabling SSH.

Reminder from testing: `uci revert` and `uci rollback` are ACL-denied, and `commit` is denied — only `apply` works, one-way. Back up first via **More → System → Backup/Reset**.

---

## 5. Corrected priority list

Re-ranked with the real UI constraints:

| # | Fix | Path | Risk |
|---|---|---|---|
| **1** | Change password | More → System → Password | none |
| **2** | Confirm HTTPS WAN stays **unchecked** | More → Network → Remote Management | none |
| **3** | 5 GHz security → `WPA2-PSK` | My Wi-Fi → Basic Settings | **drops clients** |
| **4** | 2.4 GHz width → `20 MHz`, 5 GHz → `80 MHz` | My Wi-Fi → Advanced | **drops clients** |
| **5** | 5 GHz channel → `36` | My Wi-Fi → Advanced | **drops clients** |
| **6** | Different SSIDs + separate passwords | My Wi-Fi → Basic Settings | drops clients |
| **7** | `rebind_protection=1` | §4a or §4c | none |
| **8** | `flow_offloading=1` | §4a or §4c | none |
| **9** | Disable IPv6 | More → Network → IPv6 | small |
| **10** | Add a QoS rule | More → Network → QOS | none |
| **11** | Enable Guest with a password | My Wi-Fi → Guest | none |

Steps 3–6 all bounce the radios — **do them in one sitting**, not four.

---

## 6. Things the UI confirms are already fine

Worth recording so you don't "fix" them:

- **WPS off** (`wps_enable=0`).
- **Telnet off**, **SSH off**, **FTP off**, both LAN and WAN.
- **Ping from WAN off**.
- **HTTP/HTTPS WAN off**.
- **TR-069 disabled** (`enable: 0`, `acs_url: http://`) — so finding H1 is dormant, not active. The page exists at More → System → **TR069** if you want to verify.
- **MAC/IP/URL filtering** all `mode: off` with empty lists — no stale rules.
- **Port Forwarding** empty, **DMZ** off — nothing exposed.
- **QoS** nominally on but with no rules (see M2).
- WPA3 is available in every security dropdown if your clients support it — that would be strictly better than WPA2-PSK.
