# Native 1000 ppi capture (H8)

## Result and scope

The supplied Biometrika OEM 3.3 x86 runtime can acquire 1000x1000 grayscale
images at 1000 ppi directly from the researcher's HiScan PRO. A fresh
connection followed by three automatic accepted captures was verified on
2026-10-19. Each image passed the unchanged H7 checks and was read back from
PNG. The scanner's red illumination was observed by the researcher. The
transfer returns its rows bottom-up; since the correction of the same day,
saved images have the orientation of the vendor's own 1000 DPI save, which
the earlier test images do not (see [Row order](#row-order)).

The application is our own C# program. It still depends on the installed
USB driver and the supplied OEM runtime. It does not implement a replacement
USB protocol, require the unavailable SDK development kit, or use TWAIN for
this capture path. No supplier binaries are redistributed in this repository.

All 22 PE files in the two supplied packages were inventoried and disassembled
with the already installed Microsoft `dumpbin`. The capture path, its callers,
and the relevant OEM implementations were traced in detail. Unrelated matching,
smart-card, installer, and firmware-update implementations were not fully
reconstructed. Machine-specific disassembly and analysis helpers are in
ignored `local/native-analysis/`; biometric evidence remains in `captures/`.
The file hashes, architectures and import dependencies are recorded in
[`scanner-binaries.json`](scanner-binaries.json).

## Package relationships

| Files | Role and evidence |
| --- | --- |
| `Biometrika_bus.inf`, `biometrika.cat` | USB device installation/catalog; INF identifies VID 0C43 / PID 0600 and driver package 3.3.0.2. |
| `BiometrikaDriver.exe`, `S32.upd`, `S64.upd` | Installer front end and architecture-specific setup helpers. |
| `Fxftdibus.sys`, `Fxftdibus_64.sys` | Kernel USB transport drivers. |
| `ftd2xx.dll`, `ftd2xx64.dll` | User-mode FTDI transport; the 64-bit installed DLL also uses the import name `FTD2XX.dll`. |
| `CheckPortUSB.dll`, `CheckPortUSB64.dll` | USB/platform checks used by the older OEM and setup components. |
| Driver `fxoemdll.dll`, `fxoemdll_64.dll` | OEM 3.3 capture, transfer and normalization interfaces, in x86 and x64. |
| `twBiometrika.ds` | x86 TWAIN wrapper around the OEM functions; its public capability negotiation rejects 1000 ppi on this device. |
| `FxOEMUsb.cpl`, `FxOemENU.dll`, `FxOemITA.dll` | Control-panel application and localized UI resources; includes the 1000-DPI save operation. |
| `SecBank.dll` | Separate smart-card/template functionality; not needed for acquisition. |
| `UMPI Biometric Diagnostic Tool x64.exe` | Native x64 application importing both FxISO and OEM functions. |
| `fxISO.dll` | FxISO 2.5 interface: acquisition plus vendor template/matching functions. Imports `fxISOscan.dll`. |
| `fxISOscan.dll` | Scanner layer with `FXISOSCAN_SetAcquisitionDPI`; resolves OEM operations dynamically. |
| Diagnostic `fxoemdll_64.dll` | OEM 4.2 runtime with newer USB backends and a reference to the legacy library. |
| `fxoem_legacy_64.dll` | OEM 3.7 legacy backend, importing FTDI and containing HiScan PRO support. |
| `FxISOImageTools.dll` | Image-quality evaluation, segmentation, compression and interchange helpers. |

The x64 diagnostic package demonstrates another acquisition stack, but its
binary interfaces differ from the old x86 package. The implemented route uses
the exact x86 OEM 3.3 library whose callers and ABI were recovered; it does
not mix files from these packages. Its fingerprint matching functions are
not used: the system's fingerprint methods remain those of the research (H1).

## Recovered interface

Addresses below are RVAs in the supplied x86 `fxoemdll.dll` (image base
0x10000000). They are evidence locations, not hardcoded callable addresses.
The implementation resolves named exports. Functions return a 32-bit status
with zero meaning success. Parameterized x86 exports use `stdcall`, confirmed
by their `ret N` instructions and matching call sites.

| Function | Recovered arguments | RVA |
| --- | --- | --- |
| `FXOEM_Init` | none | `0x4570` |
| `FXOEM_OpenChannel` | none | `0x58B0` |
| `FXOEM_GetScannerInfo` | output structure pointer; model byte at offset 1 | `0x2940` |
| `FXOEM_SensorConfiguration` | byte register, byte operation, ushort value, ushort* result | `0x6190` |
| `FXOEM_SetOutputDPI` | int dpi | `0x40F0` |
| `FXOEM_GetOutputDPI` | int* dpi | `0x4110` |
| `FXOEM_CaptureImage` | none | `0x5D30` |
| `FXOEM_RandomString` | byte* buffer, int length | `0x35C0` |
| `FXOEM_TransferImageNormal` | byte* nonce, byte* pixels, int* width, int* height, byte mode | `0x6AE0` |
| `FXOEM_GetLastImageNormal` | byte* pixels, int* width, int* height, int dpi | `0x3FC0` |
| `FXOEM_End` | none | `0x26D0` |

The scanner-info decoder at RVA `0xE400` writes its fields into caller-owned
storage; the application supplies 64 bytes plus a checked guard. The hardware
reports model type 8. The DPI setter's implementation at RVA `0x12790`
explicitly accepts 500 and 1000 for type 8. Its normalization-table selection
at RVA `0x15340` treats requested 1000 specially: it does not accept the
half-DPI fallback permitted for other resolutions. This supports the intended
native-detail route; it is not an independent measurement of optical MTF.

Two call sites in `twBiometrika.ds` supply the crucial acquisition details:

- RVA `0x2BC11`: after opening the channel, call
  `FXOEM_SensorConfiguration(0x32, 2, 0x80, &value)` to enable the capture
  configuration. The application's first trial omitted this call and produced
  black frames. Including it enabled the observed red illumination and valid
  fingerprint frames. The complete meaning of every register bit has not been
  reconstructed; only this supplier-used setting is applied.
- RVAs `0x2B73B` through `0x2B79A`: call `CaptureImage`, obtain a 16-byte
  nonce using `RandomString`, then pass that nonce, a pixel buffer and two
  dimension pointers to `TransferImageNormal`. The caller's default mode is 1.

The TWAIN constructor allocates only `0x4F524` (324900) bytes for its image
buffer at RVA `0x2BC32`. That is an additional reason to implement our own
buffered acquisition instead of patching a TWAIN capability constant. Our
type-8-only route supplies 4 MiB plus a checked guard and accepts exactly
1000x1000 returned pixels. It never resizes the acquired image.

The control panel's save handlers at RVAs `0x10E20` / `0x10E30` select 500 /
1000 and enter the same save routine at `0x10A60`, which passes the selected
resolution to its four-argument image-retrieval function. The x64 diagnostic
application independently confirms the zero-argument `Init`, `OpenChannel`
and `CaptureImage` calls and the five-argument `TransferImageNormal` layout.

## Row order

`twBiometrika.ds` hands the transferred frame to TWAIN as a Windows DIB. RVA
`0x25390` writes a BITMAPINFOHEADER with the returned width, a positive
height, 8 bits per pixel and 256 palette entries; RVA `0x25970` copies the
transfer buffer into the DIB's bits unchanged. A positive-height DIB stores
its bottom row first, so the OEM transfer fills rows bottom-up.

The first H8 captures stored the first transferred row at the top and are
therefore vertical mirror images of the vendor's output. A comparison with
the researcher's first left-index capture, saved through the control panel's
"Save 1000 DPI", showed it. The measure counts OpenCV SIFT matches (ratio
0.8) that agree with one similarity transform (RANSAC, 20 px). SIFT is
rotation invariant but not mirror invariant, so only images of the same
finger with the same handedness give many:

| Compared with the first left-index capture | Consistent matches |
| --- | --- |
| Four earlier H8 left-index captures, as saved | 6–7 |
| The same four, flipped vertically | 19–50 (rotation 3–5°) |
| A new capture after the correction, as saved | 29 (rotation −2°) |
| The new capture, mirrored | 8–9 |
| Other fingers of the researcher (left middle, right index) | 6–13 |

`oem-capture` now reverses the rows before the checks and saving and writes
`transfer_row_order` into each JSON file; files without it predate the
correction. The H7 checks give the same results for either row order. With
matching handedness, the estimated scale between the vendor's save and our
captures was 0.93–1.00 across placements, as expected from skin deformation;
a 500/1000 ppi mix-up would show as 0.5 or 2.

## Implemented sequence

1. Verify SHA-256 of all three local x86 runtime DLLs before loading any.
2. Load the explicit paths; initialize and open the scanner.
3. Read scanner info and refuse models other than the validated type 8.
4. Read the prior capture configuration, then apply `(0x32, 2, 0x80)`.
5. Read the prior DPI, set 1000 and require a readback of 1000.
6. Trigger acquisition, allow the configured settling interval, generate the
   16-byte nonce and transfer the full frame using mode 1.
7. Check buffer guards, returned dimensions and DPI, reverse the bottom-up
   rows, then apply H7's four image checks. Write the unchanged Gray8 values
   to lossless PNG with JSON.
8. Keep failed frames and their checks in the session's `rejected/` folder;
   continue automatically until the requested number passes or time expires.
9. Restore the prior DPI and capture configuration, close the standby channel
   and end the library session. Cleanup failures are reported.

The first frame after opening can be blank or nearly blank. It is rejected
by the same checks as any later bad frame; it is never promoted by changing
the validation thresholds. A separate worker process bounds a blocked native
call. A named mutex prevents concurrent native commands from this application.
The application binds no firmware-writing or driver-installation operations.

## Validation and remaining limits

- Direct hardware probe: type 8, 500-DPI initial setting, successful 1000-DPI
  set and readback.
- Direct acquisition: one successful capture, then three successful automatic
  captures after reopening. The repeated run also retained its rejected first
  frame. The three accepted files have distinct hashes and fine-detail metrics.
- Independent PNG readback: 1000x1000, 8-bit gray, lossless file hashes matching
  metadata. PNG encodes integer pixels/metre, so nominal 1000 ppi reads as
  approximately 999.998 ppi.
- Existing image/FFT/BMP/PNG tests pass; additional tests cover Windows worker
  argument parsing, output-folder containment and the row reversal.
- Orientation: after the correction, a new left-index capture matched the
  researcher's first capture as saved (see [Row order](#row-order)).
- Gray levels differ from the vendor's save. Around the print, 96–100 % of
  the pixels are pure white in our captures against 69–71 % in the
  researcher's first ten captures, and inside the print 15–36 % against
  11–23 %; the print covers a similar share of the frame (36–43 % against
  31–64 %). This pure white, not enlargement, raises H7's constant-block
  share (0.055–0.135 against 0.018–0.044). Whether it matters for the
  fingerprint methods is checked when they run on HiScan PRO captures.
- Negative command checks verified rejection of an altered runtime and output
  outside `captures/`. The worker deadline was exercised with a delayed worker:
  the parent stopped it after the configured deadline plus its cleanup margin.

H7's fine-detail checks are empirical tests against common 500-to-1000
enlargement artifacts, not a universal proof of optical resolution or a
fingerprint-presence/liveness detector. Validation so far covers this scanner,
the exact pinned x86 runtime, and the researcher's live test. A forced worker
termination cannot guarantee execution of native cleanup; close other scanner
applications and reconnect the device if the next open fails.

This remains the H7/H8 local capture prototype: PNG and JSON in ignored
`captures/` are not encrypted at rest. The full system's encrypted sample store,
accounts, recognition engines and UI remain governed by H1-H6 and are not
implemented by this capture tool.
