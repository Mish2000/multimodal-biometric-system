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
  timeout. The transfer's rows are bottom-up (Windows DIB order);
  `oem-capture` reverses them, so its images match the vendor's own save.
  See `scanner/README.md` and `docs/scanner-native-capture.md`.
- H9 adds `oem-guided`: finger by finger, it asks for separate placements
  (the finger lifted between them) and keeps one checked image per placement
  through the H8 worker. The second set takes three placements per finger.

## Research methods (H10)

- The research repository stays separate and is never written to. `methods/`
  imports its methods from a local checkout in the research's own Python
  environments, after checking the pin in `methods/research-pin.toml`
  (commit, SHA-256 of its artefacts outside git, plain vs plain thresholds);
  machine paths are in the ignored `local/research.toml`. Research commits
  that change only `AGENTS.md`, `README.md` or `docs/` keep the pin valid
  (H21); any other change is a new research version, which enters only by a
  new pin and a recorded decision.
- This file holds the current state of Stage B; the research repository's
  AGENTS.md points here instead of repeating it (H21).
- Run research environments' `python.exe` with the environment's folders on
  `PATH` (as `conda activate` does), or numpy's linear algebra fails to load.

## System (H11–H20)

- `docs/specification.md` is the approved specification: one PC on
  localhost (H11); separate administrator accounts, with the administration
  in the client and role checks on the server (H12); engines as child
  processes that keep no data between requests (H13); the cryptography
  (H14); the flows, thresholds and screens (H15–H18); PostgreSQL 16.15 with
  pgvector 0.8.6 from conda-forge (H19).
- The build runs in six increments (H20), each approved and reported on its
  own.

## Layout

```
docs/specification.md     the approved system specification (H11–H20)
docs/decisions.md         decision record (H1–H6 and G4 carried over; H7 on)
docs/scanner-native-capture.md  recovered OEM interface and H8 validation
docs/hiscan-methods.md    the research methods on HiScan PRO captures (H10)
scanner/ScannerCapture/   OEM and TWAIN capture tool (H7, H8, H9)
methods/                  pinned research link and its HiScan evaluation (H10)
captures/, local/         git-ignored: captures, evaluations, probe reports
```

## Commands

```bash
# .NET SDK 10 with the .NET Framework 4.8 targeting pack
dotnet build scanner/ScannerCapture -c Release -p:RestoreLockedMode=true
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe selftest
# DRIVER: the supplied fx_hs_windows_10_driver_v3.3 folder (scanner/README.md)
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe oem-probe --driver-dir DRIVER   # report in local/
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe oem-guided --driver-dir DRIVER --session live002 --fingers 1-10 --placements 3
scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe check captures/live002
# PY: the research project environment's python.exe (local/research.toml)
PY -m pytest methods -p no:cacheprovider
PY methods/hiscan_eval.py --first FIRST_SET_FOLDER   # about 5 minutes -> captures/live002/evaluation
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
- 2026-10-19 (H8 correction): those first H8 images were vertical mirror
  images of the vendor's own save, because the transfer's rows are bottom-up.
  `oem-capture` now reverses them, and a new left-index capture matches the
  researcher's first capture as saved.
- 2026-10-19 (H9): with the guided command `oem-guided` (twelve self-tests
  pass) the second set was collected: session `live002`, three separate
  placements of each of the ten fingers, 30 of 30 kept, all passing the H7
  checks on readback. Two runs failed with OEM status 110 and succeeded when
  asked again. The ignored `local/second-set-check.py` found no repeated
  placement and every image consistent with its finger label against the
  first set (`docs/scanner-native-capture.md`).
- 2026-10-19 (H10): the three research methods ran on both sets through the
  pinned link (`docs/hiscan-methods.md`). At the plain vs plain FAR 0.1 %
  thresholds OpenCV SIFT accepted 28 of 30 same-finger and 0 of 405
  different-finger pairs within the second set, but 1 of 30 same-finger
  pairs against the first set; Pore SIFT and the learned descriptor accepted
  many different-finger pairs (71 and 28 of 405), so the SD302 thresholds do
  not carry over to HiScan captures for the pore methods. A 1:1 attempt takes
  0.4 s (OpenCV SIFT) or about 3.2 s (pore detection on one CPU thread).
- 2026-10-19/20 (H11–H20): after H10 the researcher asked to stop the
  comparison experiments and build. The specification was drafted, revised
  (PostgreSQL 16.15 with pgvector 0.8.6, attempts keyed only by subject
  identifiers, the flow without enrolment, the provisional thresholds with
  their H10 counts) and approved on 2026-10-20, with the administration
  added to the client at his request. Next: increment 1, the foundation; its
  downloads await his approval.
- 2026-10-20: the public GitHub repository
  [Mish2000/multimodal-biometric-system](https://github.com/Mish2000/multimodal-biometric-system)
  was created and `main` pushed. The research repository's ten local commits
  followed the same day, so the research commit that the pin names (606c8d3)
  and the research records of H1–H6 are on GitHub too.
- 2026-10-20 (H21): the link accepts research commits that change only
  documentation, and the research repository's AGENTS.md was brought up to
  date: it keeps the research and points here for Stage B.
