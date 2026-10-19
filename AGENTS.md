# AGENTS.md

Current-state context for coding agents. Keep it short and current: update it
when a decision or the project state changes. History belongs in
`docs/decisions.md` and git.

## Goal

The identification system of Stage B of Michael Sirkovich's fingerprint
research, under academic supervision (H1–H6, G4 in `docs/decisions.md`):
login with email or username and password, then fingerprint (primary), face
and voice, each with enrolment, 1:1 verification and 1:N identification,
built as an impressive, interactive experience. The user picks the algorithm
from short accuracy, speed and how-it-works descriptions written for a simple
but curious user. The fingerprint methods come from the research repository
[fingerprint-level3-recognition-research](https://github.com/Mish2000/fingerprint-level3-recognition-research)
and take only native 1000 ppi input (its D1); face and voice use ready-made
models. The national ID is never stored. Raw samples and every attempt are
stored encrypted; decisions compare stored templates, each in its method's
native form. Every reply to the researcher is in Hebrew; code, docs and
commits stay in English.

## Working rules

- One step at a time: each approved step is reported before the next starts.
  Ask instead of assuming when a definition or constraint is unclear.
- Every decision has an ID in `docs/decisions.md`; cite it in code and
  commits. A change needs the researcher's approval and an appended entry.
- Biometric samples (fingerprint captures, face images, voice recordings) and
  anything derived from them never enter git: captures go to `captures/`,
  machine-specific files to `local/`, both git-ignored. SD302 images never
  enter the system.
- The repository is public: no local user paths in its files.
- Every download (packages, models) needs the researcher's approval; pin
  exact versions (NuGet lock files).
- Commits use the repository-local identity (Michael Sirkovich, GitHub
  noreply) without co-author trailers; the commit-msg hook strips any. Do not
  push until the researcher asks.

## Scanner (H5, H7, H8)

- Biometrika HiScan PRO on USB, reached through its 32-bit TWAIN data source
  "TWAIN Biometrika Driver" (2.2, TWAIN 2.1) and the legacy manager
  `twain_32.dll`; there is no TWAINDSM.dll on this PC.
- Probe of 2026-10-19: through TWAIN the driver offers only 500 ppi (500 is
  the only resolution, native resolution and 100 % the only scaling, in a
  1" x 1" frame) and refuses 1000; it keeps no saved settings
  (CAP_CUSTOMDSDATA) and has no custom capabilities. Its own window offers
  "Save 1000 DPI..." (the researcher's first 1000 ppi captures came from it);
  internally it uses the vendor's undocumented OEM library `fxoemdll.dll`
  (FXOEM_SetOutputDPI).
- `scanner/ScannerCapture`: console tool, C# for .NET Framework 4.8, x86,
  NTwain 3.7.6. Commands: probe, capture (no driver dialog, transfer 1.5 s
  after enabling, lossless 8-bit gray PNG marked 1000 ppi plus JSON),
  save-settings (only for sources with CAP_CUSTOMDSDATA), check, selftest.
  A capture is kept only if it is 1000x1000, reported at 1000 ppi, has ridge
  texture, and has the fine detail of a native 1000 ppi image (H7).
- H8 adds `oem-probe` and `oem-capture`: direct access to the supplied OEM
  3.3 x86 library, with exact runtime hashes, explicit sensor activation,
  1000-DPI set/readback, automatic checked PNG/JSON capture and a worker
  timeout. See `scanner/README.md` and `docs/scanner-native-capture.md`.

## Layout

```
docs/decisions.md         decision record (H1–H6 and G4 carried over; H7 on)
docs/scanner-native-capture.md  recovered OEM interface and H8 validation
scanner/ScannerCapture/   OEM and TWAIN capture tool (H7, H8)
captures/, local/         git-ignored: captures, probe reports
```

## Commands

```bash
# .NET SDK 10 with the .NET Framework 4.8 targeting pack
dotnet build scanner/ScannerCapture -c Release -p:RestoreLockedMode=true
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe selftest
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe probe            # report in local/
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe capture --session live002 --fingers 2 --attempts 3
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe check captures/live002
```

## Status

- 2026-10-19: repository created with the carried-over decisions; the capture
  tool builds, its eight self-tests pass, and its checks reproduce the
  2026-10-18 analysis of the researcher's ten first captures exactly (all
  pass). The probe shows that this driver cannot deliver 1000 ppi through
  TWAIN, so the approved route and its fallback are blocked (H7).
- 2026-10-19 (H8): the researcher reports that the vendor refused the SDK
  because the scanner is obsolete and unsupported. He approved reverse
  engineering the supplied driver and UMPI diagnostic binaries and building
  independent automatic native 1000 ppi capture outside TWAIN. That route
  now works on the connected HiScan PRO: after an initial successful capture,
  a new connection produced three accepted automatic 1000x1000 Gray8 captures
  passing the unchanged H7 checks. First frames can be blank and are rejected.
  Ten self-tests pass. The second set of ten fingers has not been collected.
- Nothing has been pushed; the GitHub repository does not exist yet.
