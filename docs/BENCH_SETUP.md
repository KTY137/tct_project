# TCT Bench Setup — Instrument LAN & Camera

Physical bench setup notes for the real hardware: restoring the instrument LAN
after a reboot/cable swap, and connecting the FLIR camera. This is operational
"how to get the real bench working" documentation, distinct from
`TCT_app/README.md` (app install/run) and `docs/ARCHITECTURE.md` (code
structure).

All facts below were verified against the real bench on 2026-07-07. Anything
not directly observed on hardware is marked `TODO: verify on the actual setup`.

See also (background/research, not step-by-step):
`docs/research/bench_lan_dhcp_static.md`, `docs/research/pdl800_trigger_wavegen_lan.md`.

---

## 1. Instrument LAN topology

The instrument LAN is an **isolated, static-IP network** — no DHCP, no
auto-discovery, no internet on this segment.

| Device | Address | Notes |
|---|---|---|
| TP-Link managed switch | `192.168.0.1` | Instrument LAN only. Has **no uplink to the office/home network or the internet**. |
| Control PC — instrument Ethernet NIC | `192.168.0.2` / `255.255.255.0` | Static, **no default gateway** set on this NIC. |
| Rigol DG4162 waveform generator | `192.168.0.10` / `255.255.255.0` | Static (DHCP and Auto IP both **OFF** on the instrument — see §3). Matches `waveform_generator.visa_address: TCPIP0::192.168.0.10::INSTR` in `TCT_app/configs/devices.yaml`. |

**Important:** this instrument LAN carries no internet traffic — internet access
comes through a separate WLAN adapter on the control PC. Do **not** set a
default gateway on the instrument NIC or on any instrument's LAN page; if you
do, Windows may prefer that route for general traffic and break normal
internet access, or instrument traffic may leak toward the wrong network.
`TODO: verify on the actual setup` if additional VISA instruments are added to
this segment — give each a static IP in the same `192.168.0.0/24` block and
add it to the table above.

---

## 2. Restore the control PC's static IP

Needed after a reboot, a driver reinstall, or if something reset the NIC to
DHCP. Run in an **elevated (Administrator) PowerShell**.

1. Check current state:
   ```powershell
   Get-NetIPConfiguration -InterfaceAlias "Ethernet"
   ipconfig /all
   ```
   Look for the adapter connected to the instrument switch. Confirm its
   friendly name — `"Ethernet"` is the verified name on the bench PC as of
   2026-07-07; `TODO: verify on the actual setup` if it has since been renamed
   (e.g. after a driver reinstall) — use `Get-NetAdapter` to list all adapters
   by friendly name if `"Ethernet"` is not found.

2. If the adapter already holds a different/DHCP address, remove it first:
   ```powershell
   Remove-NetIPAddress -InterfaceAlias "Ethernet" -Confirm:$false
   ```

3. Set the static address — **no gateway, no DNS**:
   ```powershell
   New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.0.2 -PrefixLength 24
   ```
   Equivalent `netsh` form:
   ```powershell
   netsh interface ip set address name="Ethernet" static 192.168.0.2 255.255.255.0
   ```

4. Verify:
   ```powershell
   Get-NetIPConfiguration -InterfaceAlias "Ethernet"
   ```
   Expect `IPv4Address: 192.168.0.2/24` and **no** `IPv4DefaultGateway` entry.

---

## 3. Rigol DG4162 static IP

Front-panel procedure (DG4000-series LAN menu; see
`docs/research/bench_lan_dhcp_static.md` §B.3 for the cited manual pages):

1. **Utility -> I/O Config -> LAN**.
2. Under **IP Configure Mode**, the priority is **DHCP > Auto IP > Manual** —
   turn off the higher-priority modes to force the static address to stick:
   - **DHCP = Off**
   - **Auto IP = Off**
   - **Manual = On**
3. **IP Addr**: `192.168.0.10`
4. **SubMask**: `255.255.255.0`
5. **Default Gateway**: leave at `0.0.0.0` / blank — not needed for
   same-subnet VISA traffic on this isolated bench LAN.
6. Settings are non-volatile and reload automatically on the next power-on
   (as long as DHCP and Auto IP stay Off). Re-open the LAN screen after a
   power cycle to confirm the address held.

VISA resource string (already set in `TCT_app/configs/devices.yaml`):
```
TCPIP0::192.168.0.10::INSTR
```

---

## 4. Verify the link

From the control PC:
```powershell
ping 192.168.0.10
```
A successful ping confirms the LAN path. Then connect from the app
(Waveform Generator panel, or Settings -> VISA picker) to confirm VISA itself
opens the resource.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ping 192.168.0.10` fails in both directions, but PC and DG4162 IPs both look correct | Stale VLAN configuration left on the TP-Link managed switch — silently blocks the subnet even with correct addressing on both ends. Observed and factory-reset fixed it on 2026-07-07. | Factory-reset the switch, reboot it, retest. `TODO: verify on the actual setup` — exact model/firmware and the reset-button hold time were not recorded; check the switch's physical reset button and label before resetting. |
| Ping fails, link light off on the switch or NIC | Cable unplugged, bad cable, or wrong port. | Check the physical cable/port first — cheapest thing to rule out. |
| DG4162 LAN screen shows a `169.254.x.x` address or an unexpected IP | DHCP or Auto IP was left **On** on the instrument (they outrank Manual). | Re-open Utility -> I/O Config -> LAN and confirm both DHCP and Auto IP are **Off**, then re-enter the static IP (§3). |
| PC shows the wrong/DHCP IP on the instrument NIC | Windows re-acquired a DHCP lease (e.g. after sleep/reboot) or the interface was reset. | Re-apply the static IP (§2). |
| Ping to `192.168.0.10` succeeds but the app/VISA still fails to connect | Not a network problem — VISA resource string or instrument state issue. | Confirm the resource string matches `TCPIP0::192.168.0.10::INSTR` in `configs/devices.yaml`; check the instrument isn't already claimed by another VISA session (e.g. NI-MAX). |

---

## 6. FLIR Blackfly camera

Two real-hardware requirements, both verified on the bench 2026-07-07:

1. **64-bit Spinnaker SDK.** The x86 installer does not work with the 64-bit
   Python venv this app needs for `PySpin` (see `CLAUDE.md` — numpy pin /
   cp310 win_amd64 constraint). Install the 64-bit Spinnaker SDK runtime
   before using the real-camera backend; simulation mode has no such
   constraint.
2. **Direct USB-3 port required.** The camera must be plugged into a USB-3
   port on the PC directly — connecting through a USB hub causes device
   detection to fail entirely (no camera found, even with the SDK correctly
   installed).

Symptom of either problem: the app raises `No FLIR cameras detected on USB
bus.` (from `TCT_app/devices/camera_blackfly.py`). If the SDK is confirmed
installed, move the cable to a direct USB-3 port and retry before assuming a
driver/SDK problem.

---

## 7. Waveform generator / laser-trigger safety note

**The app never auto-enables the DG4162 output on connect.** Connecting only
applies output-load/level defaults (`WaveformGenerator.connect()` in
`TCT_app/devices/waveform_generator.py`) — it never sends `OUTPut:STATe ON`.
The panel shows the output state as **unknown** until you explicitly arm it,
because the instrument can retain a prior ON state across power cycles and the
driver does not (yet) have a sourced query command to read that state back.
This is a deliberate safety property (the DG4162 output drives the PDL 800
laser trigger) — do not change connect-time behavior to force the output on
automatically. See the hardware safety rules in `CLAUDE.md`.

---

## Changelog

- 2026-07-08 (Samantha): initial version — instrument LAN static-IP topology,
  PC/DG4162 static-IP restore procedures, switch VLAN troubleshooting, FLIR
  camera SDK/USB-3 requirements, wavegen auto-enable safety note. All facts
  verified on the real bench 2026-07-07.
