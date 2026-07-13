# Bench LAN addressing: DHCP-server-on-PC vs static IPs (managed switch)

- Date: 2026-07-07
- Author: Prometheus (researcher)
- Question (from Adam / bench): Instruments (Rigol DG4162 wavegen + others) hang off
  a **managed switch** and currently self-assign **link-local 169.254.x.x** (APIPA)
  because no DHCP server answers, which breaks VISA connections. **Can we run a DHCP
  server on the Windows control PC to auto-assign IPs?** Deliver a concrete how-to
  and the recommended alternative.
- Companion note: `docs/research/pdl800_trigger_wavegen_lan.md` (Q3) already covers
  *why* mDNS/LXI auto-discovery fails through a managed switch and why static IPs are
  preferred. **This note is the actionable setup that follows.**
- Scope: addressing/connectivity only. Discovery (mDNS/IGMP) is convenience and is
  covered in the companion note; VISA works with hardcoded resource strings either way.

---

## RECOMMENDATION (read this first)

**For a fixed 3-5 instrument bench, use Path B (static IPs). Recommend it.**
Static IPs are simpler, deterministic, need no always-on server process, and cannot
create the "rogue DHCP" hazard that a PC-hosted DHCP server can. A 169.254.x.x address
just means "no DHCP answered" - the cleanest fix is to stop relying on DHCP at all and
pin each instrument.

**Choose Path A (DHCP server on the PC, with per-MAC reservations) only if** you have
many and/or rotating instruments where hand-configuring each front panel is impractical,
**and** you can guarantee the DHCP server is bound to a truly isolated instrument NIC.

**Deciding factor:** number/churn of instruments **and** whether the instrument network
is physically/logically isolated from any other DHCP server. Few, fixed instruments ->
B. Many/rotating instruments + a confirmed-isolated NIC -> A.

**Single most important safety caveat:** a PC DHCP server MUST be bound to an
instrument-only NIC that has **no path to the building/home LAN**. If it can reach a
network that already has DHCP (your home router, institute LAN), you create a second
(rogue) DHCP server that hands out wrong addresses and **breaks other machines**. Verify
isolation before enabling Path A (checklist at the bottom).

---

## Why this is happening (one line)

`169.254.x.x` = Windows/instrument APIPA fallback: the interface asked for DHCP, got no
answer, and self-assigned link-local. A managed L2 switch does **not** provide DHCP; it
just forwards frames. So either (A) provide a DHCP server, or (B) stop using DHCP and set
static IPs. Both work; they differ in robustness and risk.

---

## Path A - Run a DHCP server on the Windows control PC (what you asked for)

### A.0 Precondition (non-negotiable): a separate, isolated instrument NIC

The DHCP server must serve **only** the instrument segment. In practice that means the
instruments and the PC's instrument NIC are on their own island:

- a **second Ethernet port** on the PC (built-in + add-in card, or a **USB-to-Ethernet**
  adapter) dedicated to the bench switch, OR
- a **VLAN** on the managed switch that is isolated from any uplink to the building LAN.

The PC's *other* NIC (Wi-Fi or the primary Ethernet) keeps internet/office access; the
DHCP server is bound to the instrument NIC only. **Never** bind a DHCP server to an
adapter that reaches a network which already has DHCP.

### A.1 First set the instrument NIC to a static IP (the DHCP server's own address)

The server needs a fixed address on the segment it serves. On the instrument NIC:

- IP address: `192.168.50.1`
- Subnet mask: `255.255.255.0`
- Default gateway: **leave blank** (isolation - see checklist)
- DNS: leave blank

Windows: `Settings -> Network -> <instrument adapter> -> IP assignment -> Manual -> IPv4`,
or PowerShell (admin):
```powershell
# find the interface first: Get-NetAdapter
New-NetIPAddress -InterfaceAlias "Ethernet 2" -IPAddress 192.168.50.1 -PrefixLength 24
# (no -DefaultGateway on purpose: keeps this NIC isolated / non-routing)
```

### A.2 Option A-1: Tftpd64 (recommended DHCP-on-PC choice, already cited)

Tftpd64 (PJO2, free/open-source, Windows, portable single .exe) has a built-in DHCP
server. Install/run, then in the main window:

1. **Server interfaces** dropdown (top of the window): select the **instrument NIC**
   (the one you set to `192.168.50.1`). This is how you bind the server to that adapter
   only - **do not** pick the Wi-Fi/office NIC.
2. Open **Settings** and enable only the **DHCP** service (untick TFTP/DNS/SNTP/Syslog
   if you don't need them; leaving TFTP off avoids surprises).
3. Go to the **DHCP** tab and set:
   - **IP pool start**: `192.168.50.100`
   - **Size of pool**: `51` (yields `.100` ... `.150`)
   - **Mask**: `255.255.255.0`
   - **Def. router (Opt 3)**: leave blank or `0.0.0.0` (isolated bench, no gateway)
   - (Boot file / WINS / DNS: leave blank)
4. Bind again / restart Tftpd64 so it listens on `192.168.50.1` only.

**Per-instrument stable IPs (reservations):** Tftpd64's GUI reservation support is
limited/awkward (documented in the project issue tracker). It can hold static
MAC->IP entries via its config, but for many reservations it is fiddly. If you want
robust per-MAC reservations, prefer Option A-2.

Field names above are from the Tftpd64 DHCP setup guide (std.rocks) and the PJO2 project.

### A.3 Option A-2: Open DHCP Server (better when you need many MAC reservations)

Open DHCP Server (dhcpserver.org, free) is config-file driven and is the friendlier
choice when you want each instrument pinned by MAC. Concept:

- Set a global range for the segment, e.g. `192.168.50.100-192.168.50.150`,
  `SubnetMask=255.255.255.0`, no router option.
- Add per-MAC reservations in the host section, e.g.
  `DG4162=192.168.50.10` keyed to that instrument's MAC (read the MAC off the
  instrument's LAN screen - on the DG4162 it is shown on the LAN Setting page).
- Bind it to the instrument NIC's interface/IP so it only answers on that segment
  (Open DHCP Server has an interface/`Listen` binding for exactly this).

The result: each instrument always gets the same IP, centrally managed, server-dependent.

> Note: Windows *Server* also has a full DHCP role, but a desktop control PC almost
> certainly runs Windows 11 (no built-in DHCP role). Tftpd64 / Open DHCP Server are the
> right tools here; the Microsoft DHCP docs are for Windows Server and are not applicable
> to the bench PC except as background.

### A.4 Managed-switch gotcha: DHCP snooping can BLOCK your PC's DHCP

DHCP itself is L2-transparent (broadcast DISCOVER/OFFER on UDP 67/68 forwarded like any
frame), so a managed switch normally passes it. **But** if the switch has **DHCP
snooping** enabled, every port is **untrusted by default** and the switch **discards
DHCP server replies (DHCPOFFER/ACK) from untrusted ports** - i.e. it treats your PC as a
rogue server and the instruments never get a lease.

Fix (pick one on the switch's admin UI/CLI, on the instrument VLAN):
- **Trust the PC's port**: mark the port the control PC connects to as a DHCP-snooping
  **trusted** port (Cisco CLI example on the interface: `ip dhcp snooping trust`), or
- **Disable DHCP snooping** on that VLAN entirely (fine for a small isolated bench LAN).

If snooping is off (common default on cheap managed switches), no action needed.

### A.5 Path A trade-offs

- Pros: central management; good for many/rotating instruments; instruments stay on
  "DHCP on" (their default) so no front-panel work per unit.
- Cons: the PC must stay powered and running the server for instruments to (re)acquire;
  a second process to babysit; **the rogue-DHCP hazard if the NIC is not isolated**; and
  possible DHCP-snooping blocking on the switch.

---

## Path B - Static IPs on each instrument (STANDARD lab approach, recommended)

No server, no snooping issues, deterministic. Do this once per instrument.

### B.1 Set the PC's instrument NIC to a static IP

Same as A.1: `192.168.50.1 / 255.255.255.0`, **no gateway**, no DNS. (This is all you
need on the PC side - you are NOT running any server in Path B.)

### B.2 Set each instrument to a static IP in `192.168.50.0/24`

Pick non-overlapping addresses, e.g.:

| Instrument      | Static IP        | VISA resource string                         |
|-----------------|------------------|----------------------------------------------|
| PC (control)    | `192.168.50.1`   | -                                            |
| Rigol DG4162    | `192.168.50.10`  | `TCPIP0::192.168.50.10::inst0::INSTR`        |
| Instrument #2   | `192.168.50.11`  | `TCPIP0::192.168.50.11::inst0::INSTR`        |
| Instrument #3   | `192.168.50.12`  | `TCPIP0::192.168.50.12::5025::SOCKET`        |

Use mask `255.255.255.0` and gateway `192.168.50.1` (or blank) on every instrument.
Choose the VISA form per instrument: VXI-11 `...::inst0::INSTR` or raw SCPI socket
`...::<port>::SOCKET` (DG4162 raw SCPI port is commonly 5555; confirm per instrument -
see companion note Q3).

### B.3 DG4162 front-panel static-IP procedure (cited, not invented)

From the RIGOL DG4162 User Manual (Chapter 10, "To Configure the Remote Interface" /
LAN Setting), pages 179-182:

1. Press **Utility -> I/O Config -> LAN** to open the LAN parameters configuration
   interface (p.179). The screen shows the current **IP Configure Mode**, **Network
   Status**, **MAC Address**, and **VISA Descriptor** (pp.179-180).
2. **IP Configure Mode** offers three toggles, each **On/Off**: **DHCP**, **Auto IP**,
   and **Manual** (p.181). Priority is **DHCP > Auto IP > Manual** - so to force a
   static address you must turn the higher-priority ones **Off**:
   - Set **DHCP = Off**
   - Set **Auto IP = Off**
   - Set **Manual = On**
3. Press **IP Addr** and use the numeric keyboard + direction keys to enter the IP,
   format `nnn.nnn.nnn.nnn` (p.181), e.g. `192.168.50.10`.
4. Press **SubMask** and enter the subnet mask (p.182), e.g. `255.255.255.0`.
5. Press **Default Gateway** and enter the gateway (p.182), e.g. `192.168.50.1`
   (first octet 1-223 except 127). If your bench is isolated you may leave/enter a
   same-subnet placeholder; a gateway is not required for same-subnet VISA traffic.
6. The manual notes the entered parameters are stored non-volatile and are **loaded
   automatically on the next power-on when DHCP and Auto IP are Off** (pp.181-182).
   Power-cycle or re-enter the LAN screen to confirm the address took effect.

(No DNS field is exposed on the DG4162 LAN page per p.182 - not needed for a local bench.)

For the other instruments, use their own front-panel LAN menus (same idea: DHCP off,
set IP/mask/gateway). Do **not** invent menu paths - pull each from its manual.

### B.4 Verify

From the PC: `ping 192.168.50.10`, then open the VISA resource string in NI-MAX / your
VISA layer. If ping works but VISA does not, the address is fine and the issue is the
VISA form/port or discovery (see companion note), not addressing.

### B.5 Path B trade-offs

- Pros: deterministic; survives PC reboot/power-off; no server to run; immune to DHCP
  snooping and to the rogue-DHCP hazard; addresses never change so VISA strings are
  stable and can be hardcoded in `configs/devices.yaml`.
- Cons: a few minutes of front-panel entry per instrument; you maintain the IP list
  yourself (keep it in the table above / in the repo).

---

## What network facts decide "A vs safe" (for Adam's live diagnosis on THIS PC)

Run these on the actual control PC to confirm which path is safe. **Path A is only safe
if the instrument NIC is isolated.** Path B is safe regardless.

1. **Enumerate adapters** - is there a dedicated instrument NIC?
   `Get-NetAdapter` (PowerShell) or `ipconfig /all`. Look for a second Ethernet / a
   USB-Ethernet separate from Wi-Fi/office Ethernet.
2. **Isolation check: does the instrument adapter have a default gateway / internet?**
   `Get-NetIPConfiguration -InterfaceAlias "<instrument NIC>"` and `route print`.
   - **Safe for A**: instrument NIC has **no default gateway** (no `0.0.0.0/0` route via
     it) and only the `192.168.50.0/24` on-link route. It cannot reach the building LAN.
   - **NOT safe for A**: instrument NIC has a default gateway, or its subnet overlaps the
     office/home subnet, or the switch uplinks to a network that already runs DHCP.
     -> use Path B, or physically isolate the NIC first.
3. **Existing DHCP on the segment?** With instruments plugged in, do they get a non-
   169.254 address from *anything*? (`ipconfig` shows APIPA now, confirming *no* DHCP -
   which is exactly the reported symptom.) If some other DHCP server ever appears on that
   segment, do **not** add a second one.
4. **Switch DHCP snooping state?** Check the managed switch's admin UI/CLI: is DHCP
   snooping enabled on the instrument VLAN? If yes and you choose Path A, trust the PC's
   port or disable snooping on that VLAN (A.4). Irrelevant for Path B.
5. **Same subnet PC<->instruments?** Confirm PC instrument NIC and all instrument static
   IPs share `192.168.50.0/24` and mask `255.255.255.0` (Path B), else VISA won't reach.

Summary decision:
- Dedicated NIC, **no gateway on it**, few fixed instruments -> **Path B** (recommended).
- Dedicated **isolated** NIC + many/rotating instruments -> **Path A** with reservations.
- No isolated NIC (instrument adapter reaches office/home LAN) -> **do NOT run Path A**;
  use Path B, or add a USB-Ethernet / VLAN to isolate first.

---

## Sources

- Tftpd64 (PJO2) - free Windows DHCP/TFTP server (project page):
  https://pjo2.github.io/tftpd64/
- Tftpd64 DHCP setup - "Server interfaces" binding + DHCP tab fields (IP pool start,
  Size of pool, Mask, Def. router): https://std.rocks/windows_tftp.html
- Tftpd64 static IP reservation limitation (project issue tracker):
  https://github.com/PJO2/tftpd64/issues/19
- Open DHCP Server (free, config-file/MAC-reservation DHCP for Windows):
  http://www.dhcpserver.org/
- DHCP snooping / trusted ports - untrusted ports drop server DHCPOFFER (concept):
  https://study-ccna.com/dhcp-snooping/
- Cisco: configure a DHCP-snooping trusted interface (`ip dhcp snooping trust`):
  https://www.cisco.com/c/en/us/support/docs/smb/switches/cisco-small-business-300-series-managed-switches/smb5715-configure-dhcp-trusted-interface-settings-on-a-switch-throug.html
- Isolated-lab / rogue-DHCP warning (do not put a test DHCP server on a subnet that
  already has one): https://learn.microsoft.com/en-us/windows-server/networking/technologies/dhcp/dhcp-deploy-wps
- RIGOL DG4162 User Manual, Chapter 10 "To Configure the Remote Interface" / LAN Setting
  (Utility -> I/O Config -> LAN p.179; IP Configure Mode DHCP/Auto IP/Manual p.181;
  IP Addr p.181; SubMask + Default Gateway p.182):
  https://www.manualslib.com/manual/1416336/Rigol-Dg4162.html?page=179
- Companion note (why discovery breaks through a managed switch; VISA resource strings):
  docs/research/pdl800_trigger_wavegen_lan.md

Confidence: **official manual** for the DG4162 front-panel LAN menu (pages 179-182,
ManualsLib HTML rendering); **official docs / secondary source** for the DHCP-server
tooling (Tftpd64/Open DHCP Server) and DHCP-snooping trusted-port behavior.
