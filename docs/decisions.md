# Decision record

Decisions for the system, approved by Michael Sirkovich. Changes are appended
below with date and reason; existing entries are not rewritten.

## 2026-10-18/19 — carried over from the research repository

The system was specified in the decision record of the research repository
[fingerprint-level3-recognition-research](https://github.com/Mish2000/fingerprint-level3-recognition-research)
(`docs/decisions.md`, group H and G4) before this repository existed. Those
decisions keep their IDs and bind this repository; new system decisions
continue group H here.

- **H1** Stage B is a system build only. It embeds the research's fingerprint
  methods and replaces the 2026-10-10 task list. Fingerprint is the primary
  modality, face and voice the further ones; face and voice may use
  ready-made SDKs, while the research's D1 keeps binding the fingerprint
  methods (native ≥1000 ppi input, no reduction). The system offers
  enrolment, 1:1 verification and 1:N identification.
- **H2** Every method keeps its native template and comparison: the
  fingerprint methods compare sets of local descriptors, face and voice one
  embedding each. Templates are stored at enrolment and only the new sample
  is processed at verification or identification. Each method's template and
  comparison are described briefly to the user.
- **H3** National ID: asked once at registration, validated by its check
  digit and never stored. A keyed hash (HMAC) serves duplicate checks and
  lookups; the account links to a random identifier stored encrypted
  (AES-GCM) under a key that our own function derives from a master secret
  and a per-record random value. Keys stay outside the databases and the
  code; only standard cryptographic primitives are used. The supervisor left
  the design of this function to us.
- **H4** Stack: a React + TypeScript client packaged with Electron; a FastAPI
  server (Python 3.12); one engine process per method in its own
  environment; PostgreSQL with pgvector in two databases (accounts and
  identity link; biometric data keyed only by the random identifier); raw
  samples and the attempt history stored encrypted; OpenCV SFace with YuNet
  for face; SpeechBrain ECAPA-TDNN for voice; the Python `cryptography`
  package for every cryptographic primitive.
- **H5** Scanner: Biometrika HiScan PRO at 1000 ppi (it outputs 500 ppi
  unless 1000 is selected). The integration is designed anew; the Stage A
  TWAIN helper is not reused. It goes through TWAIN with 1000 ppi set
  programmatically and no driver dialog; the vendor's FxISO SDK (now offered
  by DigitalPlatforms) is requested in parallel and used only if it arrives.
- **H6** Defaults for the system specification, open to change there:
  templates for every algorithm of a modality at enrolment, the algorithm
  chosen at verification or identification; the user chooses the finger,
  captured three times as a quality check; the learned pore descriptor's
  second training; each algorithm decides at FAR 0.1 % with a threshold from
  SD302 development pairs until it is checked on the HiScan PRO; fusion with
  recommended weights or user weights summing to 100; every attempt stored
  (time, modality, algorithm, score, threshold, decision, duration, encrypted
  sample) with an administrator screen that shows no national IDs; SD302
  images never enter the system; no liveness detection; a Hebrew interface;
  1:1 and 1:N built as an impressive, interactive experience with texts for
  a simple but curious user.
- **G4** The system lives in this public repository,
  `C:\multimodal-biometric-system`. Its commits use the repository-local
  identity without co-author trailers.
- Stage B proceeds one step at a time; each step is reported to the
  researcher before the next starts.

## 2026-10-19 — scanner prototype

- **H7** Approved by the researcher on 2026-10-19, together with the download
  of NTwain: the repository skeleton and a console capture tool in C# for
  .NET Framework 4.8, x86 (the TWAIN data source and `twain_32.dll` are
  32-bit), with NTwain 3.7.6 from NuGet (MIT; the latest stable release, as
  4.0 is still in beta), pinned by content hash in `packages.lock.json`. The
  tool sets 1000 ppi through the TWAIN capabilities, captures without the
  driver dialog, waits 1.5 s after enabling the source before the transfer
  (the Stage A helper found that this source needs it for a good image),
  stores each capture as a lossless 8-bit gray PNG marked 1000 ppi with a
  JSON metadata file, and keeps it only if it passes four checks: size
  1000x1000, 1000 ppi reported by the source, ridge texture in the centre
  (spread of at least 20 gray levels), and fine detail of a native 1000 ppi
  image. The fine-detail check is the 2026-10-18 analysis of the
  researcher's first captures: a 1000 -> 500 -> 1000 ppi round trip keeps at
  most 0.40 of the energy above 0.25 cycles/pixel (the ten first captures:
  0.179–0.212; the same captures enlarged from 500 ppi: linear 0.476–0.954,
  cubic 0.602–0.721), and fewer than half of the 2x2 blocks in textured areas
  are constant (the captures: 0.018–0.044; pixel replication: 1.000).
  Planned fallback: the driver's saved settings (TWAIN custom DS data).
- **H7** Probe of the same day, without scanning: the driver ("TWAIN
  Biometrika Driver" 2.2, TWAIN 2.1) offers only 500 ppi through TWAIN
  (resolution, native resolution and 100 % scaling are its only values) and
  refuses 1000 (BadValue); it supports no saved settings and no
  settings-only dialog, and no custom capability in 0x8000–0x81FF answers.
  Its own window offers "Save 1000 DPI..." and shows "Real size" and "Half
  size"; internally it calls the vendor's OEM library (`fxoemdll.dll`,
  FXOEM_SetOutputDPI), for which no documentation is available. Neither the
  approved route nor its fallback can deliver 1000 ppi with this driver; the
  next route awaits the researcher's decision. All probed settings were
  returned to the driver's defaults.

## 2026-10-19 — independent native-resolution capture

- **H8** The researcher reports that the vendor declined the SDK request:
  the scanner is too old and no longer supported. He authorizes reverse
  engineering of the supplied driver and UMPI diagnostic-tool binaries to
  develop an independent application that connects, captures and saves
  native 1000 ppi images automatically, bypassing the TWAIN limitation.
  Investigate the existing local OEM and FxISO libraries and their actual
  call sequences; do not treat a DPI label or upsampling as native detail.
  Retain H7's image checks and record what is established by static analysis
  separately from what is verified on the scanner. This replaces waiting
  for the vendor SDK as the next integration step; H1-H6 otherwise remain
  unchanged. Local binary-analysis artifacts belong under ignored local/;
  captures and derived data remain under ignored captures/. Report each
  completed step before starting the next.
- **H8** Implementation and validation on the same day: the supplied x86 OEM
  3.3 runtime accepts 1000 DPI for HiScan PRO (model type 8). Reverse
  engineering its TWAIN caller recovered the required sensor-activation
  operation and acquisition ABI. `oem-probe` verifies the connection and DPI;
  `oem-capture` automatically saves lossless Gray8 PNG/JSON frames using the
  unchanged H7 checks. A hardware test succeeded, followed by three accepted
  captures after reopening; the researcher observed the scanner's red light.
  Blank first frames remain rejected and recorded. The implementation pins
  the three runtime DLL hashes, restores prior settings, isolates native calls
  in a bounded worker and keeps biometric evidence out of git. See
  `docs/scanner-native-capture.md` for the evidence and remaining limits.
