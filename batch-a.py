#!/usr/bin/env python3
"""
DWR-2000M Batch-A remediation driver.

Talks to the router over its own ubus JSON-RPC API (the same interface LuCI uses),
because this firmware exposes NO shell: SSH is firewalled, ttyd is not installed,
and rpcd's file-exec allowlist has no /bin/sh, /bin/ash or chmod.

Run from your laptop, on the LAN:

    python3 batch-a.py --dry-run     # show planned changes, touch nothing
    python3 batch-a.py --step 1      # apply one step
    python3 batch-a.py --verify      # re-read state and report

Credential is read from the ROUTER_PW environment variable, never hardcoded.
"""

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import urllib.request

BASE = "https://192.168.1.1"
USER = os.environ.get("ROUTER_USER", "admin")
PW = os.environ.get("ROUTER_PW")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPCookieProcessor(cj),
)

# Confirmed section names on this device (verified 2026-11-09):
#   firewall.cfg1292bd  name=http   src=*  dport=80   ACCEPT   <- wildcard, the bug
#   firewall.cfg1392bd  name=https  src=*  dport=443  ACCEPT   <- wildcard, the bug
#   firewall.cfg1192bd  name=ssh    src=*  dport=22   REJECT   <- wildcard, blocks SSH everywhere
#   firewall.http_lan   src=lan  dport=80   ACCEPT  (correct, pre-existing)
#   firewall.http_wan   src=wan  dport=80   REJECT  (correct, pre-existing)
#   firewall.https_lan  src=lan  dport=443  ACCEPT
#   firewall.https_wan  src=wan  dport=443  REJECT
#   firewall.ssh_lan    src=lan  dport=22   ACCEPT  (correct, pre-existing)
#   firewall.ssh_wan    src=wan  dport=22   REJECT  (correct, pre-existing)
HTTP_RULE = "cfg1292bd"
HTTPS_RULE = "cfg1392bd"
SSH_WILDCARD = "cfg1192bd"

# Wireless sections (verified 2026-11-09):
#   wireless.ra0   = 2.4G iface, encryption=psk2+tkip+ccmp  (TKIP present -> mixed mode)
#   wireless.rai0  = 5G   iface, encryption=psk-mixed+tkip+ccmp  (WPA1+WPA2 mixed)
#   wireless.ra1   = guest iface, encryption=psk2+ccmp (no key set, disabled)
#   wireless.MT7916_1_1 = 2.4G radio
#   wireless.MT7916_1_2 = 5G radio
WIFI_2G = "ra0"
WIFI_5G = "rai0"
WIFI_RADIO_2G = "MT7916_1_1"
WIFI_RADIO_5G = "MT7916_1_2"


def login():
    data = f"luci_username={USER}&luci_password={PW}".encode()
    op.open(urllib.request.Request(BASE + "/cgi-bin/luci", data=data), timeout=15).read()
    for c in cj:
        if c.name == "sysauth":
            return c.value
    raise SystemExit("login failed")


def rpc(sid, calls):
    body = json.dumps([
        {"jsonrpc": "2.0", "id": i + 1, "method": "call", "params": [sid] + c}
        for i, c in enumerate(calls)
    ]).encode()
    req = urllib.request.Request(BASE + "/ubus", data=body,
                                headers={"Content-Type": "application/json"})
    return json.loads(op.open(req, timeout=30).read())


def call(sid, obj, meth, args=None):
    r = rpc(sid, [[obj, meth, args or {}]])[0]
    if "error" in r:
        return {"_error": r["error"]}
    res = r["result"]
    if res[0] != 0:
        return {"_status": res[0]}
    return res[1] if len(res) > 1 else {}


def get(sid, cfg):
    return call(sid, "uci", "get", {"config": cfg}).get("values", {})


def setopt(sid, cfg, sec, **vals):
    """uci set takes a `values` OBJECT on this rpcd build -- not option/value strings."""
    return call(sid, "uci", "set", {"config": cfg, "section": sec, "values": vals})


def delete_section(sid, cfg, sec):
    """Delete an entire UCI section."""
    return call(sid, "uci", "delete", {"config": cfg, "section": sec})


def apply(sid):
    """`apply` == commit + reload_services. NOTE: rollback/revert are ACL-denied
    on this firmware, so apply is one-way. There is no undo."""
    return call(sid, "uci", "apply", {})


def show(sid, label, val):
    print(f"  {label:<44} {val}")


def vendor_get(sid, path):
    """Call a vendor JSON endpoint (More page API)."""
    req = urllib.request.Request(BASE + "/cgi-bin/luci/" + path)
    try:
        return json.loads(op.open(req, timeout=20).read())
    except Exception as e:
        return {"_error": str(e)}


def vendor_post(sid, path, params):
    """POST to a vendor JSON endpoint."""
    import urllib.parse
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(BASE + "/cgi-bin/luci/" + path, data=data)
    try:
        return json.loads(op.open(req, timeout=20).read())
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------- steps

def step1_firewall(sid, dry):
    """Fence the admin UI to the LAN zone.

    Also disables the wildcard SSH reject rule (cfg1192bd) which sits in the
    base INPUT chain before the zone jumps, blocking SSH from everywhere
    including LAN. The zone-specific ssh_lan/ssh_wan rules handle it properly.
    """
    fw = get(sid, "firewall")
    print("\n[1] Firewall: move http/https ACCEPT rules into the lan zone")
    for sec, want in ((HTTP_RULE, "lan"), (HTTPS_RULE, "lan")):
        cur = fw.get(sec, {}).get("src")
        name = fw.get(sec, {}).get("name")
        port = fw.get(sec, {}).get("dest_port")
        show(sid, f"{sec} ({name}, dport {port}) src", f"{cur or '(unset)'} -> {want}")
    if dry:
        return
    setopt(sid, "firewall", HTTP_RULE, src="lan")
    setopt(sid, "firewall", HTTPS_RULE, src="lan")
    print("  applying ...", apply(sid) or "ok")


def step2_rebind(sid, dry):
    """Re-enable dnsmasq DNS rebind protection."""
    dhcp = get(sid, "dhcp")
    sec = next((k for k, v in dhcp.items()), None)
    cur = dhcp.get(sec, {}).get("rebind_protection")
    print("\n[2] dnsmasq: re-enable DNS rebind protection")
    show(sid, f"dhcp.{sec}.rebind_protection", f"{cur or '(unset)'} -> 1")
    if dry:
        return
    setopt(sid, "dhcp", sec, rebind_protection="1")
    print("  applying ...", apply(sid) or "ok")


def step3_daemons(sid, dry):
    """Disable vendor debug daemons that nothing depends on.

    Deliberately excluded: atd/atcid/atci_service (may carry SMS/USSD),
    ql_netd, ql_ril_service, mnld, scd, thermal_core, mipc_* (modem/thermal).
    """
    targets = ["wfa_dut", "meta_tst", "telnetd", "vsftpd", "xl2tpd", "easycwmpd"]
    init = call(sid, "luci", "getInitList", {})
    print("\n[3] Disable vendor debug/test daemons")
    for t in targets:
        if t not in init:
            show(sid, t, "not present, skipping")
            continue
        show(sid, t, f"enabled={init[t]['enabled']} -> disabled")
        if dry:
            continue
        res = call(sid, "luci", "setInitAction", {"name": t, "action": "disable"})
        print(f"    -> {res or 'ok'}")


def step4_wifi_security(sid, dry):
    """Drop TKIP / WPA1 mixed mode on both radios.

    Live state (verified 2026-11-09):
      ra0  (2.4G)  encryption = psk2+tkip+ccmp   -> psk2+ccmp
      rai0 (5G)    encryption = psk-mixed+tkip+ccmp -> psk2+ccmp

    H3: the mixed cipher set forces the AP to disable HT/VHT/HE rates, so the
    5 GHz radio (currently 0 bytes of traffic since boot) negotiates as
    WPA1/WPA2 legacy and caps throughput at 802.11g-era speeds. Setting
    psk2+ccmp (or sae-mixed for WPA3) restores Wi-Fi 6 rates.

    NOTE: this bounces both radios and disconnects all clients. Do it in one
    sitting with the width/channel changes (step5) if possible.
    """
    wl = get(sid, "wireless")
    print("\n[4] Wi-Fi: drop TKIP / WPA1 mixed mode on both radios")
    for sec, want in ((WIFI_2G, "psk2+ccmp"), (WIFI_5G, "psk2+ccmp")):
        cur = wl.get(sec, {}).get("encryption")
        ssid = wl.get(sec, {}).get("ssid")
        show(sid, f"wireless.{sec} ({ssid}) encryption",
             f"{cur or '(unset)'} -> {want}")
    if dry:
        return
    setopt(sid, "wireless", WIFI_2G, encryption="psk2+ccmp")
    setopt(sid, "wireless", WIFI_5G, encryption="psk2+ccmp")
    print("  applying ...", apply(sid) or "ok")


def step5_wifi_widths(sid, dry):
    """Fix channel widths and pin channels.

    Live state (verified 2026-11-09):
      MT7916_1_1 (2.4G): htmode=HE40, channel=auto -> 6, ht_coex=0
      MT7916_1_2 (5G):   htmode=HE160, channel=auto -> 52, dfs_enable=0

    H6: HE40 on ch6 spans 2422-2462 MHz and overlaps a neighbour on ch4.
    H5: HE160 on DFS channel 52 with dfs_enable=0 (no radar detection).

    Targets:
      2.4G: HE20, ht_coex=1, channel=6 (pinned; ch6 is correct given neighbour on ch4)
      5G:   HE80, channel=36 (non-DFS), doth stays on
    """
    wl = get(sid, "wireless")
    print("\n[5] Wi-Fi: fix channel widths and pin channels")
    r2 = wl.get(WIFI_RADIO_2G, {})
    r5 = wl.get(WIFI_RADIO_5G, {})
    show(sid, f"{WIFI_RADIO_2G} htmode", f"{r2.get('htmode')} -> HE20")
    show(sid, f"{WIFI_RADIO_2G} channel", f"{r2.get('channel')} -> 6")
    show(sid, f"{WIFI_RADIO_2G} ht_coex", f"{r2.get('ht_coex')} -> 1")
    show(sid, f"{WIFI_RADIO_5G} htmode", f"{r5.get('htmode')} -> HE80")
    show(sid, f"{WIFI_RADIO_5G} channel", f"{r5.get('channel')} -> 36")
    if dry:
        return
    setopt(sid, "wireless", WIFI_RADIO_2G, htmode="HE20", channel="6", ht_coex="1")
    setopt(sid, "wireless", WIFI_RADIO_5G, htmode="HE80", channel="36")
    print("  applying ...", apply(sid) or "ok")


def step6_flow_offload(sid, dry):
    """Enable software (and attempt hardware) flow offloading.

    M1: sustained load average 8.5 on a 4-core CPU, zero FLOWOFFLOAD rules
    present. Even though WAN throughput is low (~1.1 MB/s avg), every
    forwarded packet traverses the software netfilter path. Enabling flow
    offloading typically cuts forwarding CPU cost by an order of magnitude.

    Try flow_offloading_hw=1 (hardware/PPE offload) -- the MT7916/MT6890
    family usually supports it. If the router rejects it, fall back to
    software-only by removing that line.
    """
    fw = get(sid, "firewall")
    # find the defaults section (anonymous, type=defaults)
    defaults_sec = None
    for k, v in fw.items():
        if v.get(".type") == "defaults":
            defaults_sec = k
            break
    cur_sw = fw.get(defaults_sec, {}).get("flow_offloading")
    cur_hw = fw.get(defaults_sec, {}).get("flow_offloading_hw")
    print("\n[6] Firewall: enable flow offloading")
    show(sid, f"firewall.{defaults_sec}.flow_offloading",
         f"{cur_sw or '(unset)'} -> 1")
    show(sid, f"firewall.{defaults_sec}.flow_offloading_hw",
         f"{cur_hw or '(unset)'} -> 1")
    if dry:
        return
    setopt(sid, "firewall", defaults_sec, flow_offloading="1",
           flow_offloading_hw="1")
    print("  applying ...", apply(sid) or "ok")


def step7_ipv6_disable(sid, dry):
    """Disable IPv6 on the LAN.

    M6: wan6 is down (NO_DEVICE), the carrier gives no prefix, but the LAN
    still hands out RA/DHCPv6. Clients get ULA addresses (fd6d:826d:6bcc::/60)
    with no route to the internet, and per RFC 6724 may prefer IPv6 and stall.

    Disabling cleanly is better than the half-on state.
    """
    net = get(sid, "network")
    dhcp = get(sid, "dhcp")
    lan_sec = "lan"  # network interface section
    odhcpd_sec = "odhcpd"
    print("\n[7] Network: disable IPv6 on LAN (wan6 is dead)")
    show(sid, "network.lan.ip6assign", f"{net.get(lan_sec, {}).get('ip6assign')} -> (remove)")
    show(sid, "dhcp.lan.dhcpv6", f"{dhcp.get(lan_sec, {}).get('dhcpv6')} -> disabled")
    show(sid, "dhcp.lan.ra", f"{dhcp.get(lan_sec, {}).get('ra')} -> disabled")
    if dry:
        return
    # remove ip6assign from the lan interface
    setopt(sid, "network", lan_sec, ip6assign="")
    # disable DHCPv6 and RA on lan
    setopt(sid, "dhcp", lan_sec, dhcpv6="disabled", ra="disabled")
    print("  applying ...", apply(sid) or "ok")


def step8_adblock_disable(sid, dry):
    """Disable adblock (enabled with zero source lists).

    L1: adb_enabled=1 but no source sections exist. It filters nothing while
    still costing memory and startup time.
    """
    adb = get(sid, "adblock")
    sec = next(iter(adb), None)
    cur = adb.get(sec, {}).get("adb_enabled")
    print("\n[8] Adblock: disable (enabled but zero source lists)")
    show(sid, f"adblock.{sec}.adb_enabled", f"{cur or '(unset)'} -> 0")
    if dry:
        return
    setopt(sid, "adblock", sec, adb_enabled="0")
    print("  applying ...", apply(sid) or "ok")


def step9_enable_ssh(sid, dry):
    """Enable SSH via the vendor's supported toggle + fix the wildcard firewall rule.

    M5: SSH is configured in dropbear but firewalled. Two problems:
      1. ssh_switch is 'off' (vendor toggle)
      2. The wildcard ssh rule (cfg1192bd, src=*) is REJECT and sits in the
         base INPUT chain before the zone jumps, blocking SSH from everywhere
         including LAN. The zone-specific ssh_lan/ssh_wan rules handle it
         properly but are dead code behind the wildcard.

    Fix: enable the vendor toggle AND disable the wildcard rule so the
    zone-specific rules take effect.

    IMPORTANT: dropbear is configured PasswordAuth=off + RootPasswordAuth=on.
    This script sets PasswordAuth=on. Test the password while the web UI is
    still open, or you'll lock yourself out.
    """
    print("\n[9] Enable SSH (vendor toggle + fix wildcard firewall rule)")
    cur = vendor_get(sid, "admin/more/ssh_get")
    show(sid, "ssh_switch (current)", cur.get("ssh_switch", "(unknown)"))
    show(sid, "ssh_switch (target)", "off -> on")

    # check the wildcard ssh rule
    fw = get(sid, "firewall")
    ssh_wc = fw.get(SSH_WILDCARD, {})
    show(sid, f"firewall.{SSH_WILDCARD} (ssh, src=*) enabled",
         f"{ssh_wc.get('enabled', '1')} -> disabled")

    if dry:
        return

    # 1. Enable the vendor SSH toggle
    res = vendor_post(sid, "admin/more/ssh_switch", {"ssh_switch": "on"})
    print("  ssh_switch result:", res or "ok")

    # 2. Tick the LAN checkbox in Remote Management
    rm = vendor_get(sid, "admin/more/remote_get")
    if isinstance(rm, dict) and "ssh" in rm:
        new_map = dict(rm)
        new_map["ssh"] = "10"  # LAN on, WAN off
        r2 = vendor_post(sid, "admin/more/remote_set",
                          {"remoteList": json.dumps(new_map)})
        print("  remote_set result:", r2 or "ok")

    # 3. Disable the wildcard ssh reject rule (cfg1192bd)
    setopt(sid, "firewall", SSH_WILDCARD, enabled="0")
    print("  disabling wildcard ssh rule ...")

    # 4. Enable PasswordAuth in dropbear
    setopt(sid, "dropbear", "cfg014dd4", PasswordAuth="on")
    print("  enabling PasswordAuth ...")

    print("  applying ...", apply(sid) or "ok")


def step10_vendor_qos_stopgap(sid, dry):
    """Configure vendor per-client QoS as the best available fix for M2.

    M2: No SQM/cake on a 16 Mbps uplink. Investigation (2026-11-09) shows
    that real SQM is NOT possible on this device:

      - sqm-scripts package: not available (OpenWrt 21.02.7 repos for this
        architecture return 404)
      - kmod-sched-cake / kmod-sched-fq_codel: not in kernel config
        (only HFSC and TBF are available, as modules)
      - tc binary: not installed (tc-tiny is in the ROM but not on PATH)
      - /proc/sys/net/* reads: ACL-blocked

    So the vendor's per-client rate limiter is the best available option.
    It caps each client to 3000 kbps down / 1500 kbps up, preventing any
    single device from saturating the uplink. The upload cap is lower because
    the uplink (16 Mbps) is the bottleneck — even 2 Mbps per client can
    saturate it with 8 clients. The download cap leaves ~6 Mbps headroom
    per client slot on the 51 Mbps downlink. This keeps navigation responsive
    when one client downloads or uploads large files, but it does NOT
    manage the queue or prevent bufferbloat the way SQM would.

    For proper SQM, you would need to:
      1. Set up a cross-compilation environment for aarch64
      2. Build sqm-scripts + kmod-sched-hfsc + tc from OpenWrt source
      3. Install manually via scp + opkg install --force-depends
    This is not practical for most users.
    """
    print("\n[10] Vendor QoS: per-client rate limits (best available for M2)")
    # get DHCP leases to build the client list
    leases = call(sid, "luci-rpc", "getDHCPLeases", {})
    v4 = leases.get("dhcp_leases", []) if isinstance(leases, dict) else []
    limit_list = []
    for l in v4:
        ip = l.get("ipaddr")
        if ip:
            limit_list.append({"ip": ip, "download": 3000, "upload": 1500})
            show(sid, f"  {ip}", "3000 kbps down / 1500 kbps up")
    if not limit_list:
        print("  no DHCP leases found, skipping")
        return
    if dry:
        print(f"  would set {len(limit_list)} per-client limits")
        return
    res = vendor_post(sid, "admin/status/qos_limit_set",
                      {"qos": json.dumps({"qosEnabled": "on", "limitList": limit_list})})
    print("  result:", res or "ok")


def step11_dns_consistency(sid, dry):
    """Make DNS policy consistent (M8).

    M8: DHCP option 6 pushes AdGuard (94.140.14.15) + CleanBrowsing
    (185.228.168.168) to clients, but the router itself resolves via ISP
    (196.203.82.66) + Google (8.8.4.4). Filtering applies to some paths
    and not others.

    Fix: remove the custom DHCP option 6 override so clients use the router
    (dnsmasq) as their DNS resolver. dnsmasq then forwards to the router's
    upstream DNS servers, making the policy consistent. This is the standard
    OpenWrt behavior and also enables dnsmasq's caching and rebind protection.
    """
    dhcp = get(sid, "dhcp")
    lan_sec = "lan"
    cur_opts = dhcp.get(lan_sec, {}).get("dhcp_option", [])
    print("\n[11] DNS: remove custom option 6 override (make policy consistent)")
    show(sid, "dhcp.lan.dhcp_option (current)", cur_opts)
    # filter out the option 6 entry, keep others (like option 26 MTU)
    new_opts = [o for o in cur_opts if not o.startswith("6,")]
    show(sid, "dhcp.lan.dhcp_option (target)", new_opts or "(none — clients use router DNS)")
    if dry:
        return
    if new_opts:
        setopt(sid, "dhcp", lan_sec, dhcp_option=new_opts)
    else:
        # remove the option entirely
        setopt(sid, "dhcp", lan_sec, dhcp_option=[])
    print("  applying ...", apply(sid) or "ok")


def step12_collectd_disable(sid, dry):
    """Disable collectd / luci_statistics (L2).

    L2: collectd and luci_statistics are enabled, writing RRD data to /tmp
    (RAM) every 30 seconds. On an already-loaded 4-core CPU this adds
    unnecessary overhead, and the data is lost on reboot. Orphaned
    collectd_iptables_match sections reference non-existent chains (br-ff).

    Fix: disable both init scripts.
    """
    init = call(sid, "luci", "getInitList", {})
    targets = ["collectd", "luci_statistics"]
    print("\n[12] Disable collectd / luci_statistics (writing RRD to RAM)")
    for t in targets:
        if t not in init:
            show(sid, t, "not present, skipping")
            continue
        show(sid, t, f"enabled={init[t]['enabled']} -> disabled")
        if dry:
            continue
        res = call(sid, "luci", "setInitAction", {"name": t, "action": "disable"})
        print(f"    -> {res or 'ok'}")


def step13_ddns_cleanup(sid, dry):
    """Delete placeholder DDNS entries (L3).

    L3: The ddns config contains myddns_ipv4 and myddns_ipv6 with placeholder
    values (yourhost.example.com, your_username, your_password). If ever
    enabled, these would publish failed-update noise and leak placeholders
    to a provider.

    Fix: delete both sections.
    """
    ddns = get(sid, "ddns")
    targets = ["myddns_ipv4", "myddns_ipv6"]
    print("\n[13] DDNS: delete placeholder entries")
    for t in targets:
        if t not in ddns:
            show(sid, t, "not present, skipping")
            continue
        show(sid, t, "exists -> delete")
        if dry:
            continue
        res = delete_section(sid, "ddns", t)
        print(f"    -> {res or 'ok'}")
    if not dry:
        print("  applying ...", apply(sid) or "ok")


def verify(sid):
    """Re-read live state. The firewall check greps the RUNTIME ruleset."""
    print("\n=== VERIFY ===")
    fw = get(sid, "firewall")
    for sec in (HTTP_RULE, HTTPS_RULE, "http_lan", "http_wan", "https_lan", "https_wan"):
        o = fw.get(sec, {})
        print(f"  firewall.{sec:<12} src={o.get('src')!s:<5} "
              f"dport={o.get('dest_port')!s:<4} target={o.get('target')}")

    out = call(sid, "file", "exec", {"command": "/usr/sbin/iptables-save"})
    txt = out.get("stdout", "") if isinstance(out, dict) else ""
    if not txt:
        print("  (could not read iptables)")
    else:
        bad = [l for l in txt.splitlines()
               if l.startswith("-A INPUT") and ("--dport 80 " in l or "--dport 443 " in l)]
        good = [l for l in txt.splitlines()
                if l.startswith("-A zone_lan_input") and ("--dport 80 " in l or "--dport 443 " in l)]
        print(f"\n  raw -A INPUT  dport 80/443  : {len(bad)}  (must be 0)")
        print(f"  zone_lan_input dport 80/443  : {len(good)}  (4 after step 1: 2 original + 2 moved)")
        for l in bad:
            print("    LEAK:", l)
        # check ssh
        ssh_leak = [l for l in txt.splitlines()
                    if l.startswith("-A INPUT") and "--dport 22 " in l]
        ssh_zone = [l for l in txt.splitlines()
                    if l.startswith("-A zone_lan_input") and "--dport 22 " in l]
        print(f"\n  raw -A INPUT  dport 22      : {len(ssh_leak)}  (must be 0)")
        print(f"  zone_lan_input dport 22      : {len(ssh_zone)}  (must be 1)")
        for l in ssh_leak:
            print("    LEAK:", l)

    d = get(sid, "dhcp")
    sec = next(iter(d), None)
    print(f"\n  rebind_protection            : {d.get(sec, {}).get('rebind_protection', '(unset)')}")
    lan_dhcp = d.get("lan", {})
    print(f"  dhcp.lan.dhcp_option         : {lan_dhcp.get('dhcp_option', '(unset)')}")

    wl = get(sid, "wireless")
    for sec in (WIFI_2G, WIFI_5G):
        o = wl.get(sec, {})
        print(f"  wireless.{sec:<5} encryption={o.get('encryption')!s:<24} ssid={o.get('ssid')}")
    for sec in (WIFI_RADIO_2G, WIFI_RADIO_5G):
        o = wl.get(sec, {})
        print(f"  {sec:<12} htmode={o.get('htmode')!s:<6} channel={o.get('channel')!s:<5} ht_coex={o.get('ht_coex')}")

    fw = get(sid, "firewall")
    defaults_sec = next((k for k, v in fw.items() if v.get(".type") == "defaults"), None)
    if defaults_sec:
        print(f"\n  flow_offloading              : {fw.get(defaults_sec, {}).get('flow_offloading', '(unset)')}")
        print(f"  flow_offloading_hw           : {fw.get(defaults_sec, {}).get('flow_offloading_hw', '(unset)')}")

    net = get(sid, "network")
    dhcp = get(sid, "dhcp")
    print(f"\n  network.lan.ip6assign        : {net.get('lan', {}).get('ip6assign', '(unset)')}")
    print(f"  dhcp.lan.dhcpv6              : {dhcp.get('lan', {}).get('dhcpv6', '(unset)')}")
    print(f"  dhcp.lan.ra                  : {dhcp.get('lan', {}).get('ra', '(unset)')}")

    adb = get(sid, "adblock")
    adb_sec = next(iter(adb), None)
    if adb_sec:
        print(f"\n  adblock.adb_enabled          : {adb.get(adb_sec, {}).get('adb_enabled', '(unset)')}")

    # collectd status
    init = call(sid, "luci", "getInitList", {})
    print(f"\n  collectd enabled             : {init.get('collectd', {}).get('enabled', '(not found)')}")
    print(f"  luci_statistics enabled       : {init.get('luci_statistics', {}).get('enabled', '(not found)')}")

    # DDNS status
    ddns = get(sid, "ddns")
    print(f"\n  ddns sections                : {list(ddns.keys())}")

    # vendor QoS status
    qos = vendor_get(sid, "admin/status/qos_limit_get")
    print(f"\n  vendor QoS                   : {qos.get('messages', '(unknown)')[:120]}")

    # SSH status
    ssh = vendor_get(sid, "admin/more/ssh_get")
    print(f"  SSH switch                   : {ssh.get('ssh_switch', '(unknown)')}")
    ssh_wc = fw.get(SSH_WILDCARD, {})
    print(f"  ssh wildcard rule enabled    : {ssh_wc.get('enabled', '1')} (must be disabled/0)")

    print(f"\n  uci pending changes          : {call(sid, 'uci', 'changes', {})}")


STEPS = {1: step1_firewall, 2: step2_rebind, 3: step3_daemons,
         4: step4_wifi_security, 5: step5_wifi_widths,
         6: step6_flow_offload, 7: step7_ipv6_disable, 8: step8_adblock_disable,
         9: step9_enable_ssh, 10: step10_vendor_qos_stopgap,
         11: step11_dns_consistency, 12: step12_collectd_disable,
         13: step13_ddns_cleanup}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--step", type=int, choices=sorted(STEPS))
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if not PW:
        sys.exit("set ROUTER_PW='your-password' first")

    sid = login()
    print(f"logged in to {BASE} as {USER}")

    if a.verify or not a.step:
        verify(sid)
    if a.step:
        STEPS[a.step](sid, a.dry_run)
        if not a.dry_run:
            print("\n--- post-change verification ---")
            verify(sid)


if __name__ == "__main__":
    main()
