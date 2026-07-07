# PDL 800 trigger input, Rigol DG4162 unipolar square, and lab LAN discovery

- Date: 2026-07-07
- Author: Prometheus (researcher)
- Questions (from Adam / bench): (1) PicoQuant PDL 800-B/-D external-trigger input spec and whether a bipolar square is safe; (2) Rigol DG4162 (DG4000 series) SCPI to make a clean 0->+V unipolar square, including the output-load/amplitude trap and duty-cycle command; (3) why mDNS/LXI auto-discovery broke behind a managed switch and how to run the bench LAN.
- Hardware: PicoQuant PDL 800-B (User's Manual v2.1 2003 / v2.2 2006) and PDL 800-D (Manual doc v2.0.4); Rigol DG4162 (DG4000-series Programming Manual, ManualsLib id 2521186).

---

## TL;DR (three actionable answers)

1. **PDL 800 trigger is safe for a bipolar +/-2.5 V square.** Both -B and -D explicitly *accept positive and negative* trigger signals into a **50 Ohm** input, with a user-set **trigger level (-1 V ... +1 V)** and pulses fired on the **rising edge** through that level. **Absolute max input is -5 V ... +5 V; exceeding that range can damage the electronics.** So +/-2.5 V is well inside spec. A unipolar 0->+2.5 V square also works (just set the trigger level to ~+1.25 V or lower). Negative excursion is allowed down to -5 V; below -5 V risks damage. Keep the source and cable **50 Ohm** to avoid reflections. Rep rate: single-shot to 80 MHz.

2. **On the DG4162, make the 0->+X V square with High/Low levels and set the output load to 50 Ohm.** Prefer `:VOLT:HIGH X` + `:VOLT:LOW 0` (defines the two rails directly) over amplitude+offset (`:VOLT X; :VOLT:OFFS X/2`) - fewer sign/half mistakes. **Critical load trap:** the DG4000 shows amplitude *for the configured load*. If its load is left at **HighZ** but it actually drives the PDL's **50 Ohm** input, the real delivered voltage is **HALF** the displayed value. Set `:OUTP:LOAD 50` so displayed == delivered into the 50 Ohm trigger input. Duty cycle: `[:SOURce<n>]:FUNCtion:SQUare:DCYCle <percent>` (20-80% for freq <=10 MHz).

3. **The managed switch is almost certainly dropping mDNS multicast (224.0.0.251) via IGMP snooping with no querier (or an mDNS/Bonjour filter).** Discovery is *convenience only* - VISA still works with hardcoded resource strings: `TCPIP0::<ip>::inst0::INSTR` (VXI-11) or `TCPIP0::<ip>::5025::SOCKET` (raw SCPI socket). For a 3-5 instrument bench, give each instrument a **static IP** (or a DHCP reservation) and hardcode the strings. To restore discovery: put PC+instruments on one VLAN/subnet and either **disable IGMP snooping** or **enable an IGMP querier** on that VLAN, and disable any mDNS/Bonjour/multicast filtering. If you need a DHCP server and the switch is L2-only, run **Tftpd64** (free, Windows, built-in DHCP) on the control PC on an isolated bench LAN.

---

## Q1 - PicoQuant PDL 800 external trigger input (laser safety, priority)

### PDL 800-B (User's Manual v2.1 / v2.2)
From the official PDL 800-B User's Manual, external-trigger section (values extracted from the manual PDF via search index; the PicoQuant PDFs would not render in-tool, see "Sourcing caveat" below):
- **Trigger level:** adjustable **-1 V to +1 V** via the trigger-level threshold control.
- **Polarity / signal type:** the input **"accepts positive as well as negative signals and features a variable trigger level, so that many different pulse shapes can effectively be used."** Pulses are emitted on the edge crossing the set level (rising/positive slope, as on the -D).
- **Absolute max input:** **"the voltage at the external trigger input connector should never exceed the range from -5 V to +5 V, otherwise the electronics may be damaged."** Max peak signal +/-5 V.
- **Impedance:** the manual requires **"the output impedance of the trigger signal source and the coaxial connector must be exactly 50 Ohm"** to prevent reflections - i.e. the input is 50 Ohm terminated.
- **Rate:** external trigger from **single shot to 80 MHz** (internal master clock f0 = 40 MHz standard, dividable by 1/2/4/8/16).

### PDL 800-D (Manual doc v2.0.4)
- **Input impedance:** **50 Ohm**.
- **Connector:** **SMA (female)**.
- **Input voltage range:** **-5 V to +5 V** (same damage limit as -B).
- **Trigger level:** adjustable **-1 V to +1 V**.
- **Edge:** laser pulses are triggered on the **rising edge** of the trigger signal.
- **Internal trigger delay:** ~**12 ns** (trigger-to-optical-pulse).
- **Rate:** single shot to **80 MHz** (full range).

### -B vs -D differences that matter
- **-D states the edge explicitly (rising edge) and the SMA-female connector + 12 ns delay** in its spec table; the **-B** phrases it as "accepts positive as well as negative signals" with a variable level rather than naming an edge. Functionally both trigger on the level crossing (positive slope).
- Both share the **50 Ohm input, -1..+1 V level range, and -5..+5 V absolute-max** figures. Treat the -5/+5 V limit as the hard damage boundary for either variant.

### Direct answer: is a bipolar +/-2.5 V square OK?
**Yes.** The input is explicitly bipolar-capable (accepts positive *and* negative signals) and rated to +/-5 V. A +/-2.5 V square sits comfortably inside the damage limit, and the negative half is not just tolerated but a documented, intended use case. Set the trigger level anywhere in -1..+1 V (e.g. 0 V or a small positive value) so the rising edge through that level fires the laser. A **unipolar 0->+V** square is equally fine. **The only hard rule: never let the input exceed -5 V or +5 V at the connector**, and keep source+cable at 50 Ohm to avoid reflection overshoot that could push a fast edge past +/-5 V.

### App-note guidance on driving from a function generator
No dedicated PicoQuant application note on "driving the PDL trigger from a function generator" was found. The governing guidance is the manual itself: any external source is acceptable provided it is **50 Ohm**, stays within **+/-5 V**, and crosses the set trigger level cleanly. `TODO(manual needed)`: an explicit **minimum trigger pulse width** figure was not located in either manual - the 80 MHz max rate implies a ~12.5 ns minimum period, but a stated minimum pulse-width spec should be confirmed from the printed manual before relying on very narrow trigger pulses.

### Sourcing caveat (honesty note)
The PicoQuant PDFs (PDL800-D_Manual.pdf, PDL800B manual, datasheet-pdl-800-d.pdf) are image/compressed PDFs that did **not** convert to readable text in-tool, and local PDF page-rendering was unavailable. The numeric values above were extracted from the **official manual PDFs via the search index** and are cross-consistent between the -B manual, the -D manual, and the -D datasheet. They are sourced (not guessed), but I could not cite exact page numbers. Confidence: official manual (values), verify page refs against the printed manuals if used for a permanent interlock.

---

## Q2 - Rigol DG4162 (DG4000 series): clean unipolar 0->+V square

All commands below are from the **RIGOL DG4000 Series Programming Manual** (ManualsLib id 2521186), quoted verbatim with the page the command reference appears on. `<n>` = channel (1 or 2). The DG4162 is a DG4000-series unit, so this manual is authoritative for it.

### Two ways to get 0 -> +X V
**(a) Amplitude + offset** (page 518 / 524):
```
[:SOURce<n>]:VOLTage[:LEVel][:IMMediate][:AMPLitude] <amplitude>|MINimum|MAXimum   # default unit Vpp   (p.518)
[:SOURce<n>]:VOLTage[:LEVel][:IMMediate]:OFFSet       <voltage>|MINimum|MAXimum    # default unit "V DC" (p.524)
```
For 0->+X: amplitude = X (Vpp), offset = X/2. Correct, but you must keep amplitude and offset in sync (offset always = ampl/2), and a sign slip flips the square below ground.

**(b) High level / Low level directly** (page 520 / 523) - RECOMMENDED:
```
[:SOURce<n>]:VOLTage[:LEVel][:IMMediate]:HIGH <voltage>|MINimum|MAXimum   # default unit V (p.520)
[:SOURce<n>]:VOLTage[:LEVel][:IMMediate]:LOW  <voltage>|MINimum|MAXimum   # default unit V (p.523)
```
For 0->+X: `:VOLT:HIGH X` and `:VOLT:LOW 0`. This names the two rails explicitly, so "0 to +X" is unambiguous and there is no offset/half arithmetic to get wrong. **Recommend method (b) for a defined unipolar 0->+X V trigger square.**

### Output-load / amplitude trap (the doubling/halving)
The DG4000 output-load command (page 202) - note it is `:OUTPut:LOAD`, not `:OUTPut:IMPedance`:
```
:OUTPut[<n>]:LOAD <ohms>|INFinity|MINimum|MAXimum      # default unit Ohm; INFinity = High Z   (p.202)
:OUTPut[<n>]:LOAD? [MINimum|MAXimum]
```
The instrument reports/settles amplitude **assuming the configured load**. Primary evidence from the same manual: the `:VOLTage:LOW` parameter range (page 523) is stated as **"-10 V (HighZ) / -5 V (50 Ohm) to the current high level"** - i.e. the same knob's limits differ by exactly **2x** between HighZ and 50 Ohm. That is the load doubling made explicit.

Consequence for driving the PDL's 50 Ohm trigger input:
- If DG4000 LOAD = **HighZ (INFinity)** but it physically drives a **50 Ohm** load (the PDL input), the real delivered voltage is **HALF** the displayed value (the internal 50 Ohm source and the 50 Ohm load form a divider).
- **Correct config:** `:OUTP<n>:LOAD 50`. Then displayed HIGH/LOW == voltage actually delivered into the 50 Ohm PDL input, so `:VOLT:HIGH 2.5; :VOLT:LOW 0` yields a true 0->+2.5 V pulse at the laser.
- If for some reason LOAD must stay HighZ, set HIGH/LOW to **2x** the desired delivered rails to compensate - but matching the load setting to reality is far less error-prone.

### Duty cycle for square
Command (page 345):
```
[:SOURce<n>]:FUNCtion:SQUare:DCYCle <percent>|MINimum|MAXimum
[:SOURce<n>]:FUNCtion:SQUare:DCYCle? [MINimum|MAXimum]
```
- Default: **50%**.
- Range is frequency-dependent: **freq <= 10 MHz -> 20% to 80%**; **10 MHz < freq <= 40 MHz -> 40% to 60%**; **freq > 40 MHz -> fixed 50%**.
- The `[:SOURce<n>]` and `[:LEVel][:IMMediate]` bracketed nodes are optional, so short forms like `:FUNC:SQU:DCYC 50` and `:VOLT:HIGH 2.5` are valid. The laser panel can set duty via this command and read back with `:FUNC:SQU:DCYC?`.

Confidence: official manual (DG4000 Programming Manual, ManualsLib), each command cited to its page.

---

## Q3 - Lab LAN behind a managed switch (brief, practical)

### Why mDNS/LXI discovery breaks through a managed switch
- Modern **LXI** mandates **mDNS/DNS-SD** discovery (multicast **224.0.0.251**, UDP **5353**); older/optional discovery is **VXI-11** (an RPC **broadcast** to UDP **111**). NI-MAX / VISA auto-discovery relies on these multicast/broadcast probes reaching the instruments.
- Managed switches commonly kill this via:
  - **IGMP snooping without an active querier:** the switch prunes multicast to "subscribed" ports; with no querier the group memberships **age out** and 224.0.0.251 stops being forwarded to the instrument ports.
  - **mDNS / Bonjour filtering** features (some switches block or gate mDNS unless a reflector is enabled).
  - **VLAN separation / port isolation** (PC and instruments end up on different subnets, or client/AP isolation drops peer traffic), and **multicast/broadcast storm-control** dropping the probes.

### Switch settings to check
- Put **PC + all instruments on the same VLAN and IP subnet**.
- Either **disable IGMP snooping** (fine on a tiny isolated bench LAN) **or** enable an **IGMP querier** on that VLAN so memberships don't age out.
- Disable any **mDNS/Bonjour filtering**, or enable the switch's **mDNS reflector/gateway** if instruments must span VLANs.
- Check **unknown-multicast flooding** behavior and **storm-control**; make sure 224.0.0.251 / broadcast RPC isn't being dropped. Disable **port/client isolation**.

### Practical recommendations (discovery is convenience, not a requirement)
- **VISA works without any discovery.** Hardcode resource strings once IPs are fixed:
  - VXI-11: `TCPIP0::192.168.0.100::inst0::INSTR`
  - Raw SCPI socket: `TCPIP0::192.168.0.100::5025::SOCKET` (use the instrument's SCPI-raw port, e.g. 5025; some use 5555/9221 - check the instrument).
- **Addressing for a 3-5 instrument bench:**
  - **Static IP set on each instrument** = most robust; resource strings never change and there's no dependency on a DHCP server being up. Best default for a fixed bench.
  - **DHCP reservations (by MAC)** = central management, still stable addresses, but requires the DHCP server to stay running.
- **DHCP server options:**
  - If the switch is **L3**, use its **built-in DHCP** (small scope on the instrument VLAN) with reservations.
  - If the switch is **L2-only**, run a tiny DHCP on the control PC: **Tftpd64/Tftpd32** (PJO2, free, open-source, Windows; built-in DHCP + TFTP; supports static reservations) is the standard lab-friendly choice; **Open DHCP Server** is an alternative. Cons: the PC must stay powered, and it will **conflict with any other DHCP** on the segment - only run it on an **isolated bench LAN** (not the building network).
- **Bottom line for this bench:** static IPs on the instruments + hardcoded VISA strings is the least-fragile setup; only stand up a DHCP server if you specifically want central lease management.

Confidence: official docs / secondary source (LXI mDNS/VXI-11 mechanism per lxistandard.org and NI VISA docs; Tftpd64 DHCP per the PJO2 project). VISA resource-string forms are standard.

---

## Sources
- PicoQuant PDL 800-B User's Manual v2.1 (2003): https://ridl.cfd.rit.edu/products/manuals/PicoQuant/PDL800B_%20manual.pdf
- PicoQuant PDL 800-B User's Manual v2.2 (2006): https://twiki.cern.ch/twiki/pub/Main/CernAtlasPixelSensorsLaserSetup/PDL800BUserManual.pdf
- PicoQuant PDL 800-D User Manual (doc v2.0.4): https://www.picoquant.com/dl_manuals/PDL800-D_Manual.pdf
- PicoQuant PDL 800-D datasheet: http://www.picoquant.com/wp-content/uploads/datasheet-pdl-800-d.pdf
- PicoQuant PDL 800-D product page: https://www.picoquant.com/products/category/picosecond-pulsed-driver/pdl-800-d-picosecond-pulsed-diode-laser-driver-with-cw-capability
- RIGOL DG4000 Series Programming Manual (ManualsLib id 2521186; pages 202, 345, 518, 520, 523, 524 cited): https://www.manualslib.com/manual/2521186/Rigol-Dg4000-Series.html
- RIGOL DG4000 Series User's Guide (load/impedance UI): https://www.batronix.com/files/Rigol/Funktionsgeneratoren/_DG4000/DG4000_UserGuide_EN.pdf
- LXI VXI-11 Discovery and Identification Extended Function (LXI Consortium): https://www.lxistandard.org/members/Adopted%20Specifications/Latest%20Version%20of%20Standards_/LXI%20Version%201.6/LXI_VXI-11_Discovery_and_Identification_Extended_Function_1.1_2022-05-10.pdf
- NI: LXI mDNS/DNS-SD vs VXI-11 discovery, VISA without discovery (raw socket string): https://forums.ni.com/t5/Instrument-Control-GPIB-Serial/LXI-mDNS-DNS-SD-implemntation-vs-VXI-11-for-its-discovery-in-NI/td-p/3636539
- Multicast/mDNS/IGMP-snooping on managed networks (why it breaks, querier fix): https://keystoneintegration.us/blog/multicast-mdns-igmp-home-network/
- Tftpd64 (PJO2) - free Windows DHCP/TFTP server: https://pjo2.github.io/tftpd64/
