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
- **H8** Correction approved by the researcher on 2026-10-19: the OEM transfer
  fills rows bottom-up, as in a Windows DIB (`twBiometrika.ds` builds a
  positive-height 8-bit DIB of the returned size and copies the buffer into
  it unchanged), but `oem-capture` stored them top-down, so its first images
  were vertical mirror images of the vendor's own save. Against the
  researcher's first left-index capture (control panel, "Save 1000 DPI"),
  counting OpenCV SIFT matches consistent with one similarity transform
  (RANSAC, 20 px): the four earlier left-index captures gave 6–7 as saved,
  the level of different fingers (6–9), and 19–50 after a vertical flip.
  `oem-capture` now reverses the rows before the checks and saving and
  records this in its JSON files. The H7 checks do not depend on row order,
  so the earlier validation stands; the earlier test images are kept
  unchanged and are mirrored. A new left-index capture with the corrected
  tool gave 29 consistent matches with the first capture as saved and 8–9
  mirrored; two other fingers of the first set gave 8–13.

## 2026-10-19 — second capture set

- **H9** Approved by the researcher on 2026-10-19: the second capture set of
  his ten fingers (session `live002`) takes three separate placements per
  finger, the finger lifted off the glass between them, as in H6's enrolment
  default of three captures per finger. Frames taken back to back from one
  placement (H8's `--attempts`) are nearly identical and are not separate
  impressions: the three frames of H8's repeat test, about 2 s apart, have a
  pixel correlation of 0.94–0.99 without any alignment, against 0.20–0.49
  between separate placements of the same finger. A guided command,
  `oem-guided`, asks for each finger and
  placement in turn and runs the unchanged H8 worker for one accepted image
  per placement; it records the placement in the file name and JSON and
  resumes an interrupted session after the highest kept placement. Running
  the research's methods on these captures is a separate later step.

## 2026-10-19 — the research methods on HiScan PRO captures

- **H10** Approved by the researcher on 2026-10-19: the two repositories stay
  separate. The system uses the research's methods through a pinned, checked
  link (`methods/research-pin.toml`): the research checkout must be at the
  pinned commit with no change to tracked files, its artefacts outside git
  (the learned descriptor's second training, the plain vs plain evaluation)
  must match their SHA-256, and the `fpl3` package each research environment
  imports must come from that checkout. The research code is never copied or
  changed, nothing is written into the research repository, and a new
  research version enters only by a new pin with a recorded decision; machine
  paths stay in the ignored `local/research.toml`. The research repository's
  G4 (it stays the research home and the source of the methods) stands.
- **H10** The first use of the link, approved the same day: OpenCV SIFT, Pore
  SIFT and the learned pore descriptor (second training) run unchanged, each
  in its research environment, on the second set (H9) and on the first set:
  (A) placements of the second set against each other, the earlier capture as
  reference (30 same-finger and 405 different-finger pairs), and (B) the first
  set as reference against the second set (30 and 270), each counted at the
  plain vs plain operational thresholds at FAR 0.1 % (RxJ and QxJ), with pore
  counts, single-thread timings (the learned descriptor on the GPU) and
  template sizes. Fusions are left out for now. The different-finger pairs
  are one person's other fingers, so they cannot confirm FAR 0.1 %. Results
  are in `docs/hiscan-methods.md`.

## 2026-10-20 — the system specification

Approved by the researcher on 2026-10-20 together with
`docs/specification.md`, which holds the details. After H10 he asked to stop
the comparison experiments and build the system; the draft of 2026-10-19 was
revised before the approval, because conda-forge's Windows build of pgvector
0.8.6 needs PostgreSQL 16.15 rather than 18.6, attempts must name people only
by subject identifiers, and the camera and microphones had only been found
present. He left the open questions to the specification.

- **H11** One PC runs the whole system: the researcher's PC with the HiScan
  PRO, its integrated camera and its microphones. The server listens on
  127.0.0.1 only.
- **H12** User accounts are registered in the client with the national ID
  and hold the biometric functions. Administrator accounts are separate and
  administrative only, with no national ID and no biometric data
  (privileged work apart from everyday accounts, as in NIST SP 800-53
  AC-6(2)). The first administrator is created by a server command; at the
  researcher's request the administration also lives in the client, so the
  separation can be shown in use: administrators sign in on the same login
  screen and get the administration area (accounts, attempt history,
  thresholds, audit log), create further administrators with a one-time
  password that is changed at the first sign-in, and disable or re-enable
  accounts, never the last active administrator. The server checks the role
  on every request and refuses by default; administrative changes ask for
  the password again and enter an audit log.
- **H13** Engines are long-running child processes of the server that keep
  no data between requests; each message on standard input and output is a
  JSON header followed by its binary data, and the CPU engines compare 1:N in
  parallel worker processes. They need only the standard library beyond
  their method, so the research environments stay unchanged. A new
  acquisition mode of ScannerCapture returns each image and its checks on
  standard output and writes no file.
- **H14** Cryptography, all from the `cryptography` package: HMAC-SHA256 of
  the national ID under its own key; per-record keys from HKDF-SHA256 of the
  master secret with a random 32-byte salt and a label per use; AES-256-GCM
  for the identity link, raw samples, attempts and fingerprint templates,
  each ciphertext marked with its key version and bound to its row as
  associated data; passwords with Argon2id at RFC 9106's second recommended
  option (3 passes, 4 lanes, 64 MiB, 128-bit salt, 256-bit tag), with failed
  sign-ins slowed down; random session tokens stored only as hashes; face and
  voice embeddings in pgvector columns under subject identifiers only. Keys
  live in a file outside the repository that only the Windows user can read,
  with a backup kept by the researcher.
- **H15** Verification and identification in a modality need the user's own
  enrolment in it; otherwise the system offers to enrol now or to return to
  the home screen (the supervisor's flow of 2026-10-18). A fingerprint
  enrolment is kept only when its three captures match pairwise with OpenCV
  SIFT at its threshold, else one more placement is asked for. 1:1 compares
  the new capture with the three templates of the finger the user picks, and
  the highest score decides; 1:N compares it with every enrolled template,
  and the top candidate is reported only when it passes the threshold, else
  "not found".
- **H16** Thresholds are settings that administrators can change in the
  client, each change audit-logged. Initial values: OpenCV SIFT above 57
  (SD302 plain vs plain, FAR 0.1 %, RxJ); provisional Pore SIFT above 37 and
  learned descriptor above 21, just above the highest different-finger
  scores of H10. In H10 these values accept 28, 13 and 24 of 30 same-finger
  pairs and none of 675 different-finger pairs, which claims no FAR. Fusion
  thresholds are set by the same rule from H10's saved scores when fusion is
  built. Calibration with other people is not part of the build; it is a
  separate step if the supervisor asks for accuracy on the HiScan PRO.
- **H17** Face and voice enrolment take three images or three recordings of
  about four seconds.
- **H18** For the drawings the engines also return matched coordinates; only
  the research score decides. In 1:N results other users appear as "another
  registered user", and drawings use only the user's own prints. The
  algorithm choice shows OpenCV SIFT first (the only threshold that is not
  provisional on the HiScan PRO, the best HiScan result and the fastest 1:1),
  then the learned pore descriptor, Pore SIFT and the fusions. Until the
  thresholds are calibrated with other people, the cards show the SD302
  plain vs plain results as the accuracy, since that sample is far larger
  than H10's (the researcher's choice).
- **H19** PostgreSQL 16.15 with pgvector 0.8.6 from conda-forge, started by
  the server under the user's account, so no Windows service and no
  administrator rights are needed; Docker's `pgvector/pgvector` image is the
  fallback.
- **H20** The build proceeds in six increments, each working end to end with
  automated tests and approved and reported on its own: the foundation with
  accounts, roles and login; fingerprint enrolment and 1:1 with OpenCV SIFT;
  all fingerprint algorithms, the choice, 1:N and the drawings; face; voice;
  the rest of the administration area, fusion and the finished experience.
