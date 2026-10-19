# Settings — chamber LAN auto-detection

## Scope

The administrator-only **Settings → Chamber configuration → Auto-detect chambers**
button discovers Vötsch/Weiss S!MPAC/LabEvent TCP devices on the *server's*
network interfaces, not the browser's. The server can be disconnected from the
Internet. The GUI calls the installed external
`VotschTechnikClimateChamber.discovery.discover_chambers` only through
`chamber_web.adapters.votsch`, injected from `chamber_web.main` into the
generic NiceGUI page; the GUI contains no independent protocol socket code.

## Workflow

1. Sign in as an administrator; select **Auto-detect chambers**.
2. Leave the CIDR blank to inspect the server's detected RFC1918 /24
   interface networks (up to 512 hosts total), or restrict the scan explicitly
   to a private /24 or narrower CIDR such as `192.168.10.0/24`.
3. Review IP, driver-reported model and serial. A silent device or model that
   does not support the expected protocol is not listed.
4. Press **Select** to put the IP address, expected serial and chamber type
   into the existing *unsaved* configuration form. The existing chamber ID,
   temperature safety envelope and operator-presence acknowledgement are
   deliberately unchanged.
5. Review the chamber identity and site-approved temperature range, provide
   physical supervision acknowledgement, enter the administrator password and
   save. Restart the server to apply the configuration. The single-active-
   physical-chamber limit remains unchanged.

A scan never authorizes chamber connection, profile execution or unsafe
control. Administrator permission is rechecked at discovery and selection.
Saved `CHAMBER_HIL_*` settings do not override explicit environment variables.

## Boundaries and risk

- Driver-owned read-only `GET CHAMBER INFO` model and serial queries only,
  using TCP port 2049. No START/STOP, setpoint writes, relays or gradients.
- Opt-in only, from an authenticated ADMIN session; other roles cannot scan.
- 16 concurrent probes; up to 512 private IPv4 hosts, 350ms socket timeout and
  12s driver watchdog. GUI also enforces a 15s response deadline.
- One discovery operation at a time per server; each worker closes sockets.
- No automatic acceptance of an advertised serial: the persisted serial pin
  and current HIL safety protections remain mandatory.
- The automatic interface selection uses up to two local /24 networks (not
  all possible routed networks). NAT/VLAN isolation or blocked TCP/2049 can
  cause missed devices. A scan can return partial results on timeout.
- Only use discovery against lab networks where you have permission to query
  equipment. Real-hardware compatibility requires supervised site verification
  against exact models/firmware; automated CI uses mocks and simulation only.

## Dependencies

The GUI's `requirements-hardware.txt` pins the reviewed external driver
revision that provides this API. An older driver has no discovery API and the
UI shows a clear unavailable message rather than falling back to raw sockets.
Windows packaging collects the external driver when hardware dependencies
are included; the simulation-only bundle does not include the driver.

## Test coverage

- Driver: rejected public CIDRs, bounded host enumeration, mock protocol
  identity, socket release and offline unit tests on Python 3.8/3.10/3.12.
- GUI: adapter-only driver delegation, concurrent scan rejection, browser
  administrator selection without saving or connecting and existing
  architecture-import-boundary checks.
- Physical HIL tests are **not** performed by this PR and require separate
  signed site authorization.
