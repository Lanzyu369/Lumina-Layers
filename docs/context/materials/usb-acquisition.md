# LuminaBox USB acquisition

The public Box workspace collects one material's reflection readings on black
and white backings. The instrument performs sampling, calibration and percentage
calculations; Studio persists the readings and builds the material archive.

## Using the connection

1. Use a data-capable USB cable and firmware supporting `lumina-box` version 1,
   2 or reliable transport version 3. The v3 envelope retains v2 measurement rules;
   older one-way firmware remains supported with an explicit compatibility status.
   Close serial monitors before connecting; a serial port can be occupied by
   another application.
2. Open the updated Lumina Studio desktop application, or use desktop Chrome
   or Edge at localhost or an HTTPS URL.
   On the Lumina Box page, enter the current material identity and select the
   USB device using Connect. Selection always starts from that user action.
   The desktop application uses Node SerialPort in an isolated Electron utility
   process; Chrome/Edge retain their Web Serial permission chooser.
3. Complete the hardware calibration. Select `Trans Cal` on the device with the
   optical path empty and confirm to capture and save its transmission XYZ/lux
   reference. Startup loads the saved reference without measuring again; leaving
   a sample inside during power-on must not replace it. After migrating from
   ESPHome, perform all three calibrations; its preference storage is not imported.
   Upgrading earlier native firmware preserves its reflection white/black data,
   but requires one initial manual `Trans Cal` because its transmission reference
   was previously held only in RAM. A confirmed save failure preserves the last
   successful values. `Save unverified` means the current values remain in use,
   but startup might load the new values; repeat calibration until `Saved`.
   Transmit/Auto require a valid transmission reference;
   reflection alone does not.
   Calibrate before a batch. If recalibrating partway through, remeasure the
   affected rows: the saved reference does not recalculate existing table values.
4. Current seven-selection firmware uses `0.08, 0.16, 0.24, 0.32, 0.64,
   1.28, 2.00` mm. In the **Lumina Box** workspace these values are
   overlay thicknesses; the complete sample is always 3.00 mm. Select Reflect
   for this workflow. Bare W3/K3 targets are selected separately in Studio,
   with the original device-selected thickness retained unchanged.
   Historical firmware/records retain the earlier twelve selections.
   Confirming a result returns to thickness selection with the previous thickness
   highlighted. Confirm the thickness again to start the next measurement.
5. Continue measuring on the Box. Review the saved table, generate the material
   profile and save it to the library. Switching materials or backings waits for
   pending writes and changes the capture identity while keeping USB connected.

Reference-relative reflection readings may exceed 100. They remain unchanged
in capture records and enter fitting as measured. Transmission from Auto frames
is retained in the original device message; only reflection enters this workflow.

The desktop application supplies its own device chooser. Device access is
limited to the trusted main application frame; Workshop modules cannot request
a port. After updating the desktop main process, restart the application to
load the chooser (frontend hot reload alone does not update it).

Browsers without Web Serial, insecure remote HTTP pages, or hosts that do not
expose serial permissions cannot use this connection. Manual entry remains
available. A browser device chooser must not be bypassed by backend port scans.

## Wire contract, versions 1 and 2

Transport: UTF-8 JSON, one object per LF-terminated line (CRLF accepted), serial
port opened at 115200 baud. Byte chunks are not messages: a line may arrive in
several reads, or several lines in one read. Non-protocol diagnostic lines may
be ignored. Oversized and malformed frames must not partially update a row.

Example (all readings are percentages, not ratios or raw sensor counts):

```json
{"protocol":"lumina-box","version":2,"type":"measurement","measurement_id":"boot-a-1","thickness_mm":3,"mode":"auto","reflectance_xyz":[103.2,98.5,101.1],"transmittance_xyz":[1.2,2,1.7]}
```

| Field | Meaning |
| --- | --- |
| `protocol`, `version`, `type` | Exactly `lumina-box`, numeric `1` or `2`, `measurement` |
| `measurement_id` | Nonempty ID unique across measurements and hardware restarts |
| `thickness_mm` | Positive finite physical thickness; must match one table row |
| `mode` | `auto`, `reflect`, or `transmit` |
| `reflectance_xyz` | Three finite, non-negative numeric percentages in X/Y/Z order; required for auto/reflect; version 1 also caps each at 100 |
| `transmittance_xyz` | Three finite numeric percentages in X/Y/Z order; required for auto/transmit |

T is in `[0, 100]` in both versions; R is in `[0, 100]` in v1 and finite/non-negative
in v2. No numeric strings, NaN, infinity, RGB conversion, automatic scaling, or
fallback-to-zero is permitted. A measured T=0 is retained unchanged in the original device message.
Calibration and incomplete or failed measurements are not measurement frames.
Auto publishes only when both halves have completed successfully.

An out-of-range T means a channel's current reading exceeds its empty-path
reference. Check placement, remove the sample and run `Trans Cal` manually,
then repeat the measurement. Restarting only reloads the stored reference.

The device creates one logical result per successful measurement. Studio deduplicates the
most recent 512 applied IDs within the persisted capture batch; a repeated recent ID must
not overwrite manual edits. IDs are bounded to 128 characters.
Firmware uses a per-boot identifier plus a monotonically increasing sequence.
Received values remain raw percentages. Reflection maps to
`reflectance_percent_xyz` without clipping or further normalization, while the
complete original device frame is retained alongside the saved reading.

## Reliable native USB transport, version 3

Studio persists a capture UUID and applied receipts. Changing material or backing
rotates the UUID after pending writes have settled. A v3 `hello` requests that scope, and only a matching
`pong` establishes a healthy connection. Device identity must match a previous
peer within the same batch. Older firmware falls back after 2.5 seconds to a
visibly unverified compatibility mode; a known v3 peer never silently downgrades.

Commands use `protocol: "lumina-box"`, `version: 3`, `type`, `capture_id`.
The device accepts only hello/ping/ack/reject/replay, with bounded ASCII tokens.
Delivery adds `type: "delivery"` and `measurement: <original v2 object>`.
Pong includes boot_id, pending_count, dropped_count, tx_failures, last_measurement_id
and last_ack_id. There is no remote sampling or calibration command.

The device retains up to 32 results in RAM, awaiting application ACK in completion
order with 0.5/1/2/4-second retry spacing. Writes and USB flushes alone do not
retire a result. Queue overflow evicts the oldest and increments a visible counter.
Power loss removes the RAM queue; calibration/NVS is untouched. No results from
before the first capture handshake are automatically imported.

Studio ACKs only after the backend durably saves the reading and Studio updates
the local capture receipt. Previously applied IDs re-ACK without changing manually edited values.
Missing or ambiguous thicknesses and storage failure send reject, keeping that
result paused. After correcting the table, Retry pending results sends replay;
this explicit action can replace that row. Reconnect alone does not resume rejects.
Old-scope frames cannot restore cleared data or enter a new material.

One-second ping/pong maintains a six-second lease. Idle links remain healthy.
Recoverable read faults adopt an actual replacement stream. Heartbeat loss permits
at most two reopens of the same previously authorized port after successful cleanup;
no background device scanning or permission chooser is used. The desktop native
worker has a two-second operation deadline and is terminated on a stalled native
operation. The parent waits for process exit before completing cleanup or reopening
that port. The frontend's 2.5-second deadline remains a boundary guard. Browser
Web Serial retains ownership until its platform operation finishes. Development
module replacement disconnects stores; main-frame navigation or renderer loss
also revokes desktop grants and terminates their workers.

The independent `lumina-box-reliable-firmware.jsonl` C++ fixture covers pong and all
36 v3-wrapped measurements, including zero transmission and reflection above 100.

## Verification boundary

Automated coverage must include split UTF-8/JSON lines, mixed logs, invalid
frames, duplicate IDs, the seven acquisition thicknesses, earlier firmware
compatibility, fit invalidation, disconnect/unmount and capture-identity changes.
Hardware acceptance additionally requires actual USB enumeration, calibration
persistence after power loss, all seven physical selections, and values matching
the OLED.
Mock serial streams and a successful firmware build do not establish sensor
accuracy or prove a physical USB connection.

The checked-in `lumina-box-firmware-v1.jsonl` test fixture preserves the original
LuminaBox C++ serializer output, covering all twelve thicknesses in all three
modes. Keep it as the old-firmware compatibility baseline. The separate v2
fixture comes from the current serializer and includes R above 100. Generate
current output with `python firmware/tests/run.py --fixtures <output>` in the
LuminaBox checkout, then copy the bytes into the v2 fixture, never over v1.
Firmware-wire tests exercise the real frame parser; backed-gradient capture tests
exercise reflection placement and durable-save routing;
generating both producer and consumer fixtures with JavaScript would not verify
the firmware's number formatting or field names.
