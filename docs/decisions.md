# Decision record

Decisions for the system, approved by Michael Sirkovich. Changes are appended
below with date and reason; existing entries are not rewritten.

## 2026-10-18/19: carried over from the research repository

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
  `C:\multimodal-biometric-system`.
- Stage B proceeds one step at a time; each step is reported to the
  researcher before the next starts.

## 2026-10-19: scanner prototype

- **H7** Approved on 2026-10-19, together with the download
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

## 2026-10-19: independent native-resolution capture

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
- **H8** Correction approved on 2026-10-19: the OEM transfer
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

## 2026-10-19: second capture set

- **H9** Approved on 2026-10-19: the second capture set of
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

## 2026-10-19: the research methods on HiScan PRO captures

- **H10** Approved on 2026-10-19: the two repositories stay
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

## 2026-10-20: the system specification

Approved on 2026-10-20 together with
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

## 2026-10-20: documentation changes in the research repository

- **H21** Approved on 2026-10-20, amending H10's check so
  that the research repository's documentation can change without a new pin: the research
  checkout must descend from the pinned commit, and every tracked file outside
  its documentation (`README.md` and `docs/`) must be the pinned
  commit's, committed or not; the pinned artefacts keep their SHA-256 check
  and `fpl3` must still come from that checkout. A research commit that
  changes only documentation therefore needs no new pin, while a change to
  code, configurations, environments, manifests or tests still needs a new
  pin and a recorded decision. The pin keeps naming the commit that produced
  H10's results.

## 2026-10-20/21: the server of increment 1

- **H23** Approved on 2026-10-21 with the server of
  increment 1 (H20), within H3, H4, H12, H14 and H19. He approved the
  downloads on 2026-10-20; the component library left that list for H22.
  - Environments: `multimodal-server` and `multimodal-postgres`, conda-forge
    only, each with an explicit lock (SHA-256 per package) in `environments/`;
    the client's npm packages in `client/package-lock.json`. Every version is
    the newest stable one published at least 14 days earlier, transitive npm
    packages included (resolved with `--before`).
  - PostgreSQL: one cluster in `local/postgres/data` on localhost:55432 with
    SCRAM passwords, started by `pg_ctl` under the user's account. The
    databases `mbs_accounts` and `mbs_biometric` each have their own login
    role and are closed to every other role; pgvector is in the biometric one.
    libpq's GSSAPI encryption is switched off, as it crashes the process with
    libpq 18.6 from conda-forge on this PC.
  - The key file is `%LOCALAPPDATA%\multimodal-biometric-system\keys.json`,
    with inherited permissions removed and only the current user allowed; it
    is never replaced automatically.
  - Parameters: passwords of 12 to 256 characters after NFKC normalisation,
    with no composition rules; sessions end after 30 minutes without use and
    after 12 hours at most; after five failed sign-ins for one name, each try
    waits 2, 4, 8 ... seconds, at most five minutes; usernames of 3 to 32
    letters or digits of any script, with `.`, `_` and `-` inside; usernames
    and emails unique regardless of case.
  - Subjects carry no creation time, so they cannot be matched to accounts by
    it; a trigger keeps the audit log insert-only; the API answers errors as
    codes that the client turns into Hebrew text.

## 2026-10-21: light and dark themes

- **H24** Approved on 2026-10-21: the researcher and the supervisor want
  users to choose between a light and a dark look. As in large current
  systems, the client's settings menu offers three themes: light, dark, and
  Windows' setting, which is the default. The choice is saved per account, so
  each user of the PC keeps their own, and it applies at once; the sign-in
  and registration screens, before anyone has signed in, follow Windows'
  setting. Every screen is designed in both themes, so the choice of design
  direction (H22) does not depend on it.

## 2026-10-21: the exact data model

- **H25** Approved on 2026-10-21, for the supervisor's
  request of an exact table structure that holds several findings per
  person: `docs/data-model.md` gives every table, column, type, key and
  sealed value of both databases, refining section 4 of the specification.
  A person is one subject; each finger, the face and the voice is an
  enrolment of it; each enrolment holds its findings, the samples, which are
  sealed raw captures; and each finding has one template per method. Within
  H3, H14 and H15–H17:
  - The thresholds live in an `algorithm` table, the catalogue of the
    methods with their versions, in place of the specification's threshold
    table.
  - One template table serves the three modalities: sealed bytes for
    fingerprints, an unsealed pgvector embedding for face and voice (H14).
  - Enrolling the same finger, face or voice again marks the old enrolment
    as replaced instead of deleting it, so its findings and the attempts that
    used them stay.
  - An enrolment keeps only its three captures that pass the checks; a
    capture that H15's pairwise check rejects is not kept.
  - An attempt seals its capture, while its outcome (score, threshold,
    decision, times) stays unsealed so that the administration area can
    filter the history; this is how H14's sealed attempts are read.
  - In 1:N the attempt keeps the top candidate's enrolment, and so its
    subject and finger.
  - Every sealed value is bound to its person: the subject identifier is
    part of the associated data, so a finding or template moved to another
    subject does not open.
  - Findings come only from the PC's scanner, camera and microphone; taking
    them from files would add a `source` column.

## 2026-10-22: the client's skeleton

- **H26** Approved on 2026-10-22: the client's skeleton is
  built before the supervisor chooses the design direction and the component
  library (H22), so that increment 1 works end to end in the client:
  sign-in, registration, the replacement of a one-time password, the home
  screen, the administration area of increment 1 and the settings, in a
  neutral look that the chosen direction replaces. Within H4, H11, H12, H14
  and H24:
  - The main process is the client's only network client and keeps the
    session token, which never reaches the page. The page runs sandboxed,
    isolated and without Node.js, and reaches the main process only through
    a preload bridge that offers named routes from a fixed list and the
    theme; its Content Security Policy keeps it from connecting anywhere
    itself. The window cannot be navigated away or open other windows, and
    every permission request (camera, microphone, ...) is refused until a
    modality needs one.
  - The screens use hash navigation and read the account's role and
    one-time password only to choose what to show; the server decides every
    request (H12).
  - During development the server runs on its own (`python -m mbs serve`),
    at 127.0.0.1:55433 unless `MBS_SERVER_URL` names another address. The
    client's start and stop of the server (specification, section 3) follow
    as a step of their own: the client will start the server only when it
    does not answer, and stop only a server it started.
  - `serve` brings the tables up to date before it answers, so a newer
    server, such as this one with the account's theme (H24), upgrades the
    databases when it first starts.

## 2026-10-23: findings from files

- **H27** Approved on 2026-10-23, answering H25's open
  question (on 2026-10-22 he said that findings may also come from files): a
  face image or a voice recording may be taken from a file as the new
  finding of a 1:1 verification or a 1:N identification. Within H6, H14, H17
  and H25:
  - Face and voice only. A fingerprint always comes from the scanner, whose
    captures H7 checks; a file cannot show that it was captured natively at
    1000 ppi (D1).
  - Verification and identification only. Enrolment, the reference that
    every later comparison relies on, takes its findings from the PC's
    camera and microphone alone: without liveness detection (out of scope,
    H6), an enrolment from a file would let anyone enrol another person from
    a picture or a recording.
  - The files accepted: faces as JPEG or PNG, up to 10 MB, at least 240
    pixels on the short side and at most 50 million pixels (OpenCV's
    `OPENCV_IO_MAX_IMAGE_PIXELS`), with exactly one face found; voices as
    WAV, MP3 or OGG, up to 10 MB and 3 to 30 seconds long, decoded with
    libsndfile and converted to 16 kHz mono. M4A (AAC) and HEIC would need
    further decoders (FFmpeg, a HEIF library) and are not accepted. The
    exact libraries come with the download lists of increments 4 and 5.
  - The server recognises a file by its content, never by its name or the
    type the client states, checks its size before reading it whole, and
    decodes it in the modality's engine. Only the normalised finding is
    kept, sealed like a capture from the device: the image's pixels as PNG,
    which drops metadata such as a GPS position or a camera's serial number,
    and the recording as 16 kHz mono WAV. Neither the original file nor its
    name is kept.
  - The attempt records where its finding came from: `attempt.source`,
    `device` (the default) or `file`, created with the table in increment 2,
    and a check in the database keeps fingerprint attempts to `device`.
    `sample` is unchanged, since enrolment takes no files.
  - The upload stays out of sight until someone looks for it, the
    progressive disclosure that large products use for rare alternatives:
    the capture from the device is the only prominent action, and no
    button, link or drop area for files shows by default. A small "more
    options" button (⋯) beside the device's view opens a menu whose one item
    takes a file, with a line saying that a file can also be dragged onto
    the window; a file dragged over the window shows the drop target only
    while it is dragged. Enrolment's pages offer neither. The result names
    its source, and the administration's history can filter by it.

## 2026-10-24: the password in the settings

- **H28** Approved on 2026-10-24: a screen of its own for changing the
  password is needless: as in large products, an account
  changes its password in the settings. Their first area keeps the theme
  (H24); the second, security, asks for the current password and the new
  one twice, and says that the change signs the account's other sessions
  out. The bar after sign-in no longer links to a password screen. A screen
  of its own stays only for the one-time password, which an account must
  replace before anything else (H12); once it is replaced, the route sends
  the account to its landing, where the old address of that screen leads
  too.

## 2026-10-24: wording of process notes

- Wording of process notes edited for publication; no decision, design or
  result changed.

## 2026-11-04: sign-up, sign-in and password recovery

Approved on 2026-11-04, from the supervisor's meeting of that day, before
increment 2 starts: the sign-up and sign-in screens are brought to what a
current product offers, and nothing else changes.

- **H29** Registration asks for a mobile phone number, where the SMS of H32
  goes. The server keeps it in E.164 form (a plus sign and 8 to 15 digits),
  unique like the email. A number written the national way (05X-XXXXXXX) is
  taken as an Israeli mobile, as the national ID is Israeli too (H3), and an
  Israeli number in international form must be a mobile as well.
  Administrator accounts have no phone (H12), and accounts registered
  before H29 have none, so they recover their password by email only.
- **H30** Replacing the password parameters of H23 (12 to 256 characters,
  no composition rules): a password has 8 to 32 characters after NFKC
  normalisation, with at least one uppercase letter and at least one digit.
  Lowercase letters and other characters (punctuation, symbols, spaces) are
  optional and make it stronger. Every new password (registration, the
  settings' security area, the replacement of a one-time password and
  recovery) shows a meter that changes with every character typed, in the
  supervisor's four levels: invalid (a rule is broken), weak (neither
  optional kind), medium (one of the two) and strong (both); letters without
  case, such as Hebrew ones, count as neither. Under it the three rules and
  the two options are listed and marked. The server checks the rules; the
  meter is the client's alone. Every password field has an eye that shows or
  hides what is typed. Passwords set before H30 keep working until they are
  changed.
- **H31** Amending section 1 of the specification, where the interface was
  Hebrew: the client is in English by default, with Hebrew, right to left,
  as the other choice. Before sign-in, the sign-in and registration screens
  have a switch. Registration saves the screen's language in the account; a
  sign-in saves a language chosen on the sign-in screen, and without one the
  account keeps its own. Signed in, the settings change it, like the theme
  (H24). After sign-out the screens stay in the last language, and a new
  start of the client is in English.
- **H32** An account that is signed out can recover its password. A line
  under the sign-in button leads to the recovery screen, where the user
  chooses an SMS to the registered mobile phone or an email to the
  registered address, and types that number or address. As OWASP's Forgot
  Password Cheat Sheet advises, the answer is the same whether the details
  belong to an account or not; the link carries a random 256-bit token,
  stored only as its SHA-256, that works once and for 30 minutes, and only
  an account's newest link works; an account gets at most one message a
  minute; the new password follows H30, with its meter; afterwards every
  session of the account ends, and the user signs in as usual. The link is
  the client's own type, `mbs://reset-password`, which the client registers
  for the current Windows user, so a click opens the client at the screen
  of the new password; the main process keeps the link's token as it keeps
  the session's (H26). The message is in the language of the screen that
  asked for it, and so is that screen. No SMS provider or mail server is
  chosen yet (the researcher's choice of 2026-11-04): every message is
  written as an HTML page to the git-ignored `local/outbox/`, and the
  server's window names each new file. Real sending can later replace the
  outbox without changing the screens; a link opened on a phone cannot reach
  this system, whose server listens on 127.0.0.1 only (H11), so a real SMS
  will need a code or a reachable address instead.

## 2026-11-05: fingerprint enrolment and its quality check

Approved on 2026-11-05: the first step of increment 2 is the enrolment alone;
verification (1:1) follows as its own step.

- **H33** A fingerprint enrolment is generic, as H6 asks: it keeps the three
  raw captures of the finger, sealed, and every method makes its templates
  from them, so a method added later needs no new enrolment. In this step
  only OpenCV SIFT makes templates; Pore SIFT and the learned descriptor make
  theirs from the same captures in increment 3.
  - **The same finger (H15):** OpenCV SIFT is the fixed referee, not a choice
    of the user, since its threshold is the only one on the HiScan PRO that
    is not provisional (H16) and it did best there (H10). Every pair of the
    three captures must score above its threshold, the later capture as the
    probe and the earlier as the reference, as in H10. When no three of the
    captures kept so far do, one more placement is asked for, and the three
    whose lowest pair score is highest are kept. After 6 kept placements or
    12 captures without three that match, the enrolment ends unsaved.
  - **Quality:** every capture that passes H7's checks is scored with NIST's
    NFIQ 2.3.0, the reference implementation of ISO/IEC 29794-4, from 0 to
    100. NFIQ 2 is defined for 500 ppi, so the score is computed on a copy
    reduced by the mean of every 2 x 2 block, in memory and for the score
    only; the methods keep the native 1000 ppi capture (the research's D1).
    A capture scoring below 35, or one NFIQ 2 cannot score, is not kept, and
    the finger is placed again. The minimum is provisional: the researcher's
    40 captures scored 39 to 91 (median 64.5), so none falls below it, while
    synthetic damage to copies of them put 4 of 40 blurred copies and 11 of
    39 partial ones below it, and one partial copy got no score. The score
    is kept with H7's checks in the sample's `checks`.
  - **NFIQ 2's build:** the released 2.3.0 C interface cannot load the 2.3
    model (a stale checksum, NIST's issue 409, fixed in its source on
    2026-09-30 without a release), and the released command-line tool reads
    only files, which H13 rules out. The system therefore uses NIST's v2.3.0
    source with only that fix (commit 6ebcd52, one line), built as a library
    without the command-line tool, so of the tag's components only OpenCV
    4.10.0, FingerJet FX OSE and digestpp are needed (`engines/README.md`).
    Nothing is installed into Windows. From memory the build gave exactly the
    released tool's scores on all 40 captures and on the damaged copies.
  - **Acquisition (H13):** `ScannerCapture oem-acquire` waits either for a
    placed finger, returning its checked image, or for the finger to be
    lifted, which it reports after two frames in a row without ridge
    texture, since a new connection's first frame can be blank (H8). It
    writes JSON lines to standard output, an image's PNG right after its
    line, and no file. The server is its watchdog, stops it when an
    enrolment is cancelled, and retries a run that fails with OEM status 110
    once (H9).
  - **Engines (H10, H13):** `engines/opencv_sift.py` runs the research's
    OpenCV SIFT through the pinned link, its comparison and seeding
    unchanged. The research's extraction reads a file, so the engine decodes
    the PNG in memory and makes the same OpenCV call; a test shows equal
    points and descriptors, and on the second set (H9) the engine gave H10's
    scores on all 435 pairs. `engines/nfiq2_quality.py` runs NFIQ 2. Both run
    in the research project environment, which has numpy, and add nothing to
    it; the server's environment does not change.
  - **Live progress:** amending section 3 of the specification, an
    enrolment's progress comes as a streamed HTTP answer of JSON lines, not
    WebSocket messages: once started, the flow goes one way, and the session
    token and the route's role check stay those of every other request
    (H12, H26). Closing the connection cancels the enrolment and stops the
    scanner.
  - **The stored template:** at the end of an enrolment the client shows how
    it is stored, in six steps: the captures with their checks; OpenCV SIFT's
    points; one point's 128 numbers in SIFT's own layout (4 x 4 cells of 8
    orientation bins), as a strip and as numbers; the whole template as a
    picture; the template's row with its sealed value split into its parts;
    and the pair scores against the threshold. The server sends this once,
    from its memory before sealing, only to the user who enrolled; no stored
    template is opened for it, as only engines read templates (H14), and the
    page keeps it only while the screen is open. Showing it again later
    would need a decision of its own.
  - **Tables (H25):** `algorithm` (the four fingerprint rows with H16's
    values; face and voice join when their models are pinned), `enrolment`,
    `sample` and `template` are built as in `docs/data-model.md`; `attempt`
    comes with verification. A new enrolment of the same finger replaces the
    old one, which stays with its findings. Administrator accounts cannot
    enrol (H12).

## 2026-11-05: deleting a fingerprint enrolment

Approved on 2026-11-05.

- **H34** On the fingerprint screen, a user who chooses an enrolled finger
  can delete its enrolment as well as enrol it again, and is not made to
  enrol it again. After a confirmation, every enrolment of that finger of
  the user, the current one and those it replaced (H33), is erased from the
  biometric database with its sealed captures and templates, so nothing of
  that finger stays; the finger counts as not enrolled until it is enrolled
  again. Other fingers and other people are untouched. The route is
  `DELETE /api/fingerprint/fingers/{finger}`, for user accounts only (H12).
  Attempts do not exist yet; verification will settle what an attempt keeps
  when its enrolment is deleted.

## 2026-11-06: fingerprint verification

Approved on 2026-11-06: implement the next fingerprint step, verification
(1:1), with a guided functional client. The visual direction follows the
functional build. The deletion rule below was approved explicitly the same day.

- **H35** A user chooses an enrolled finger and takes one new capture. The
  same H7 checks and NFIQ 2 minimum of 35 from H33 apply. A rejected capture
  asks for a lift and another placement, with at most 12 captures per run.
  NFIQ 2 uses its in-memory 500 ppi copy only; matching uses native 1000 ppi.
  - The server opens that finger's three current OpenCV SIFT templates,
    checks their version against the engine, and compares the new template
    with each. Only the new capture is extracted. The highest score decides,
    strictly above the threshold read at the start of the attempt (H15, H16).
    The research's defined comparison failures count as zero, as in H10;
    scanner, engine, encryption and storage errors end the run with an error.
  - Migration `biometric_0003` creates `attempt` as in H25 and H27. Every
    completed comparison, accepted or rejected, stores its score, threshold,
    decision, processing time and probe. The probe is sealed under
    `mbs/probe/v1`, bound to the attempt and its subject. Processing time
    starts when the accepted capture arrives, includes quality, extraction
    and comparison, and ends before storage. Quality-rejected captures and
    cancelled or failed runs have no comparison outcome and create no attempt.
  - `POST /api/fingerprint/verifications` is for user accounts only, with the
    same authenticated streamed JSON-line response as enrolment. Both flows
    share the scanner lock. Cancellation stops the scanner. Before storing,
    the server checks that the compared enrolment is still current; a deletion
    or replacement during the run invalidates it. A completed result is sent
    only after storage commits. A connection lost at completion can leave a
    saved attempt whose result did not reach the client.
  - The client shows the chosen finger, real capture, quality and comparison
    progress, cancellation, retries and the saved result. The result gives
    all three scores, the deciding score and threshold, and processing time;
    capture checks are available in its details. An unenrolled finger offers
    enrolment or a return home (H15). The screens work in English and Hebrew
    and in both themes, using the existing neutral appearance. Match drawings
    remain in increment 3 and the administrative history screen in increment 6.
  - Amending H34's open question: deleting a finger erases the verification
    attempts of its current and replaced enrolments, including their sealed
    probes. The foreign key uses `ON DELETE CASCADE`. Re-enrolment still keeps
    the earlier enrolment and its attempts. The deletion confirmation states
    this scope. The retention of identification attempts is settled when 1:N
    is implemented.

Validation on 2026-11-06 uses throwaway databases, synthetic protocol inputs
and the real engines on existing HiScan captures. Manual validation of the
integrated flow with a finger on the scanner follows separately.

## 2026-11-07: scanner connection recovery and cancellation cleanup

Approved on 2026-11-07: investigate a scanner that stopped responding in both
enrolment and verification, and correct the handling to prevent recurrence.

- **H36** The device was present and healthy according to Windows, while
  `FXOEM_OpenChannel` returned OEM status 110. The unchanged acquisition code
  from the last published version reproduced the error directly, including
  its retry. Restarting the USB device through Windows did not recover it;
  physically disconnecting and reconnecting it restored successful opening
  and lift detection. The user then confirmed it was working again.
- The initiating event could not be established. Five controlled forced
  cancellations followed by reopening did not reproduce the stuck state.
  However, cancellation used an immediate process kill, which skips native
  disposal and can leave scanner settings and its channel unclosed. H35 made
  disconnect cancellation immediate, exposing that existing cleanup risk.
- The server now requests cancellation by closing the worker's standard
  input. `oem-acquire --cancel-stdin yes` observes this between native calls,
  restores the settings and closes the channel before exiting with code 4.
  All native calls and disposal stay on one thread. A 10-second cleanup
  watchdog forces termination only when the worker cannot finish.
- Persistent open-channel status 110 is reported distinctly and logged as an
  operation/status pair. No software reset that recovered the observed stuck
  state was established; physical reconnection remains the recovery for that
  state if graceful cleanup cannot prevent it. The diagnostic message says so.

## 2026-11-07: switch off the scanner at the end of acquisition

Approved on 2026-11-07: restore the scanner's idle illumination behavior.

- **H37** The red illumination remained on with no acquisition worker running.
  The connected HiScan PRO returned `0x80` from capture register `0x32` at
  open, compared with `0x00` in the healthy H8 probe. Cleanup in the published
  version and the local build restored the saved value. Once a run started
  with `0x80`, every completed run restored the enabled state. The event that
  first left the register enabled was not observed.
- The vendor's TWAIN data source writes `0x00` through
  `FXOEM_SensorConfiguration` before closing the channel (`twBiometrika.ds`
  RVA `0x2B533`). The OEM tool now uses that shutdown write on a validated
  HiScan PRO channel before restoring the prior DPI and closing the channel.
  The value read at open remains available in the probe for diagnosis.
- On the connected scanner, the first corrected close cleared `0x80` to
  `0x00`, and the red illumination was confirmed off. Completing a lift
  wait, cancelling it through standard input and letting it time out each
  left the register at `0x00` and allowed the next open to reach 1000 DPI.
  All 15 scanner self-tests passed.

## 2026-11-07: live fingerprint verification check

The OpenCV SIFT 1:1 verification flow (H35) passed a manual check on the
connected HiScan PRO after H36 and H37. A read-only check of the local
biometric database confirmed saved verification outcomes with sealed probes.

## 2026-11-07: Pore SIFT verification and method choice

Approved on 2026-11-07: the first task of increment 3 adds Pore SIFT to 1:1
verification and lets the user choose between it and OpenCV SIFT.

- **H38** Both methods use the generic enrolment of H33. OpenCV SIFT remains
  the fixed same-finger referee for enrolment. When the Pore SIFT runtime is
  configured, a new enrolment creates its three Pore SIFT templates after the
  referee has chosen the three captures. Both methods' templates and the
  samples commit together, so a failed extraction preserves the prior enrolment.
- An existing enrolment gets missing Pore SIFT templates at its first
  verification with that method. The server opens the three sealed samples
  in memory and shows preparation progress before asking for a new capture.
  The new templates commit together, under their method's label and version.
  A retry reuses prepared templates. A deletion or replacement before the
  preparation commits invalidates the operation. Preparation is serialized
  with capture through the existing service lock and rechecked under a row
  lock, including when another process prepares the same enrolment.
- The Pore SIFT engine imports the research worker and its upstream code
  from the pinned checkout, in its existing Python 3.10 environment. A short
  startup check in the research project Python verifies the pin, upstream
  revisions and tracked files, and resolves the configuration. The model's
  SHA-256 and loading checks remain those of the research worker.
  Detection, NMS, coordinate ordering, preprocessing, descriptors and the
  basic matcher keep their research functions and parameters. NMS image
  output is discarded and its coordinate text is held in memory. The engine
  adds no dependency and keeps no sample or template between requests.
- Templates retain the research's native NPZ layout, with integer pore
  coordinates and float32 descriptors, sealed in the existing template table.
  Verification extracts only the new capture and compares it with the three
  stored templates of the selected method. The highest score decides. The
  attempt records the selected algorithm and its threshold. H16's initial
  Pore SIFT threshold remains provisional, accepting strictly above 37.
- The client defaults to OpenCV SIFT. Its method choices describe accuracy
  on SD302, estimated processing time and how the method works, with the
  current threshold from the server. SD302 accuracy refers to other scanners
  at the research thresholds. The Pore SIFT result marks the local threshold
  provisional and names the score as matched pores. Preparation, cancellation,
  retry and results work in both languages and themes. The template screen
  identifies which methods' templates were prepared. Its detailed point/vector
  demonstration continues to show OpenCV SIFT.

Validation uses stored HiScan captures and synthetic inputs. All 30 second-set
templates have exactly the research's points and descriptors; all 435 pair
scores equal H10. Live scanner validation of the new method follows separately.

## 2026-11-07: learned pore verification and generic enrolment clarity

Approved on 2026-11-07: add the second trained pore descriptor to 1:1
verification and clarify the separate roles of enrolment and method choice.

- **H39** The learned descriptor imports the pinned research's second model,
  window selection, description and matching functions in its existing GPU
  environment. The model and research pin are verified before use. Native
  templates remain NPY arrays of 128-value float16 descriptors, as in H10.
  Extraction uses the same detected pores as Pore SIFT. No dependency is
  downloaded and no research source or model is changed.
- New enrolments prepare all available methods after the unchanged OpenCV
  SIFT referee chooses the three captures. Pore SIFT's extracted coordinates
  feed the learned descriptor directly, without another detection. Each
  additional method compares the three placement pairs for illustration;
  these scores do not decide whether to accept the enrolment. All captures
  and templates commit together, preserving the previous enrolment on failure.
- Existing enrolments receive missing learned templates before their first
  verification with that method. When a sample already has a current Pore
  SIFT template, its coordinates are reused; otherwise the shared detector
  returns coordinates from memory. Preparation is atomic, version-checked,
  cancellable and invalidated by deletion or replacement, following H38.
- Learned verification compares the new capture with the three stored
  learned templates, taking the highest score. H16's provisional threshold
  remains strictly above 21. The selected method, threshold, result and
  sealed probe enter the existing attempt table, following H35.
- The client places method choice inside verification, with an explicit
  start before capture. Enrolment explains its fixed referee and its generic
  templates. The completion screen labels the OpenCV SIFT template
  demonstration and separates the enrolment check from the other methods'
  placement-pair scores, each with its own threshold and provisional flag.
  Both languages and themes retain the existing functional appearance.

Validation uses synthetic inputs and existing HiScan captures; the integrated
scanner flow is left for the manual check after implementation.

The process protocol also releases request-local input and output references
before waiting for the next message, including error replies (H13, H39).
The learned adapter reproduced all 30 second-set templates exactly and all
435 H10 pair scores. Automated validation passed 141 server tests, including
both real-engine enrolment shapes, 84 client tests, 9 engine tests, 7
research-link tests and 63 offscreen client checks. Type checking and the
client build passed. Offscreen checks covered all three methods, old-template
preparation, new generic enrolment, the method labels and pair-score
separation, both languages and themes, and cancellation. No live scanner
test was run during this validation.

## 2026-11-07: manual fingerprint check and method-change shortcut

The H39 implementation passed a manual check on the connected HiScan PRO.

Approved on 2026-11-07.

- **H40** A matched 1:1 result offers `Change method` between `Verify again`
  and `Back to the fingers`. It opens the existing method selection while
  keeping the chosen finger and the previous method selected. The catalog
  is refreshed, and a new capture starts only after `Start verification`.
  The new attempt has a fresh run identifier; late events from the earlier
  attempt cannot change its screen. Labels are English or Hebrew and use
  the existing light and dark styles.

The existing bilingual verification checks now cover the action order, the
preserved finger, the explicit capture start and isolation from earlier
events. All 84 client tests, type checking and the build passed.
The shortcut also passed a manual check on the connected HiScan PRO.

## 2026-11-07: fingerprint identification with OpenCV SIFT

Approved on 2026-11-07: implement OpenCV SIFT 1:N before face and voice,
following H20. On the same date, identification history and its sealed
probes were explicitly retained when a leading enrolment is deleted.

- **H41** A signed-in user with at least one enrolled finger starts an
  identification without choosing a finger. The gallery contains the
  current fingerprint enrolments of active user accounts, resolved through
  their encrypted identity links. Each enrolment must have three complete,
  version-compatible OpenCV SIFT templates. Gallery metadata and the
  method's threshold are fixed at the beginning of the attempt.
- Capture uses H7 and H33, including the NFIQ 2 minimum of 35 and at most
  12 captures. The new accepted capture is extracted once. Up to four
  independent instances of the pinned OpenCV SIFT engine compare it with
  stored native templates. Each group opens at most four references in
  memory. Each enrolment receives its highest score, and the highest gallery
  score decides, strictly above the snapshotted threshold (initially 57).
  Defined comparison failures score zero. Technical failures end the run
  with an error and create no comparison record.
- The search uses the gallery fixed for that attempt. Additions are included
  in the next search. Before saving, the server locks and rechecks all
  participating accounts and enrolments, including template membership and
  version. A completed deletion, replacement or account deactivation
  invalidates the result. The scanner lock is shared with enrolment and
  verification. Cancellation interrupts computation and waits for worker
  cleanup before releasing the lock. Progress reports completed comparisons.
- Every completed search, including a non-match, stores an identification
  attempt with the caller's subject, leading enrolment, number of compared
  templates, score, threshold, decision, processing time and sealed probe.
  The result reaches the client after the transaction commits. The client
  receives the five highest-ranked enrolments and the total count. It sees
  only the caller's own finger names. Other candidates have a rank for this
  attempt and the label `Another registered user`.
- Equal highest scores are reported explicitly as tied leaders. Enrolment
  UUID orders ties deterministically for storage and ranking. The client
  indicates that a unique candidate has not been selected. UUIDs of gallery
  subjects, accounts, enrolments and templates stay on the server.
- Migration `biometric_0004` changes `attempt.top_enrolment_id` to
  `ON DELETE SET NULL`. Deleting an enrolment keeps identification attempts,
  their outcomes and their sealed probes, including attempts made by other
  users, and removes the link to the deleted enrolment. H35 continues to
  delete that enrolment's verification attempts. The deletion confirmation
  describes both rules.
- The client offers an explicit start, real capture and search progress,
  cancellation, retry, a ranked result and capture details in English and
  Hebrew, with both themes. Search progress uses a visual pass over the
  gallery driven by completed comparisons. The detailed match drawings
  remain a later task of increment 3.

Validation passed 168 server tests, including migration of existing attempts,
parallel-search cancellation and equality with serial OpenCV SIFT comparison
of stored HiScan templates. All 93 client tests, type checking and the build
passed. The offscreen client passed 64 checks with a two-account throwaway
database, real engines and existing captures. It covers own and other-user
matches, no match, cancellation and retry, both languages and themes, the
minimum window width and correct 1:N notation in Hebrew. Manual validation
with the scanner follows separately.

## 2026-11-07: live OpenCV SIFT identification check

The OpenCV SIFT 1:N identification flow (H41) passed a manual check on the
connected HiScan PRO.

## 2026-11-07: fingerprint identification with pore methods

Approved on 2026-11-07. Extend H41 identification to Pore SIFT and the
learned pore descriptor, including method selection and preparation of
missing gallery templates from sealed captures.

- **H42** The identification screen lists the available methods before an
  explicit capture start. It uses the same method catalog as verification.
  Its accuracy figures describe SD302 pair comparisons. The time estimates
  describe extraction and one comparison from H10. OpenCV SIFT is the default.
  The result uses the selected method's score label and threshold, including
  the provisional status of the pore thresholds. Changing the method returns
  to the choice screen and requires an explicit start for the next attempt.
- The search fixes its gallery and selected threshold at the start. When
  selected pore templates are missing, the server opens the enrolment's
  sealed captures in memory before requesting a new scan. Learned templates
  reuse pinned Pore SIFT coordinates when present. Otherwise the pinned
  detector produces the coordinates. The new templates keep the research
  format and are sealed to their row, subject and method (H39).
- Preparation reports progress across the gallery. It commits missing
  templates together for each enrolled finger. Cancellation or failure leaves
  completed enrolments available to the next search. A changed or removed
  enrolment invalidates preparation for that finger. Deletion and template
  storage lock the enrolment before writing or deleting related rows.
- OpenCV SIFT and Pore SIFT compare bounded groups with up to four CPU
  processes. The learned descriptor uses one runtime for comparison and the
  shared detector for extraction. Identification compares the selected
  method's templates and records that method and its threshold. Acceptance
  remains strictly above the snapshotted threshold (H16). H41 applies to
  ranking, anonymity, timing, consistency checks and attempt retention.

The full server run passed 197 tests with existing captures. Prepared pore
templates matched the H10 reference templates, and the tested rankings matched
serial comparisons. A concurrent deletion test reproduced a database deadlock.
After the lock order fix, all 27 focused server tests passed, including the new
concurrency test. All 101 client tests, type checks and build passed. The built
client passed 73 offscreen checks with both languages and themes, a two-account
gallery, real engines and existing captures. Manual scanner validation follows.

## 2026-11-08: live pore identification check

Pore SIFT and learned pore 1:N identification (H42) passed manual checks
on the connected HiScan PRO.

## 2026-11-08: OpenCV SIFT verification match illustration

Approved on 2026-11-08. Add a functional illustration of the OpenCV SIFT 1:1
comparison, with the new capture, the highest-scoring stored capture and
the point pairs included in that score (H18, H35).

- **H43** The engine observes the pinned comparison's call to OpenCV and
  its returned RANSAC mask. A scoped OpenCV binding delegates the calls and
  records the coordinates selected by that mask. The original binding is
  restored on exit. The comparison's returned score determines the result.
  With `view = true`, the response includes one little-endian float32 row
  per counted inlier, containing probe x/y and reference x/y coordinates.
- Verification requests this data for its three OpenCV SIFT comparisons.
  It keeps the highest-scoring set of pairs. Equal scores use the earliest
  stored placement. The server validates the pair count against the score
  and validates the coordinates in the native 1000-pixel frames. It opens
  the corresponding sealed sample only from the caller's current enrolment.
  Technical or encryption failures follow H35's failed-run handling.
- The final response includes the stored image and match pairs after the
  attempt commits. The illustration is available for both matches and
  completed non-matches. A zero score shows the two images with an empty
  set of counted pairs. The page keeps the illustration for the current
  result and clears it on retry, method change or navigation.
- The client shows the two native image frames side by side, with all
  counted connections and one highlighted pair. A pointer over either
  image selects its nearest matched point. A keyboard-accessible slider
  selects a pair, and a checkbox controls the full set of lines. The image
  coordinate frames run left to right in both interface languages. The
  controls use the existing light and dark themes, following H35.

Validation reproduced all 435 second-set H10 scores. Each comparison's
reported pair count equalled its score, and every reported coordinate
belonged to the corresponding native template. The full server run passed
206 tests. After the processing-time boundary adjustment, 26 focused
verification tests passed. All 11 engine tests, 107 client tests, type
checks and the build passed. The offscreen client passed 69 checks with
real engines and stored captures, including the match illustration in both
languages and themes. Manual scanner validation follows separately.

## 2026-11-08: live OpenCV SIFT match illustration check

The OpenCV SIFT 1:1 match illustration (H43) passed a manual check on the
connected HiScan PRO.

## 2026-11-08: pore match illustrations in verification

Approved on 2026-11-08. Extend the H43 illustration to Pore SIFT and the
learned pore descriptor in 1:1 verification (H18, H43).

- **H44** Both pore scores count mutual nearest descriptor pairs that pass
  the 0.7 distance ratio check, without a geometric check. The illustration
  shows exactly those pairs at their native pores, and the page states the
  counting rule of each method, so crossing pore lines are read correctly.
- Pore SIFT templates hold their points. With `view = true`, a scoped
  binding observes the list that the pinned matcher's
  `find_correspondences` returns and its score counts, and is restored on
  exit. The list's length must equal the score. Each tuple's probe and
  reference indices map to (row, column) pores, sent as x and y.
  Verification asks for this in each scoring comparison, as H43 does.
- Learned templates hold descriptors only. After the three scoring
  comparisons, the server repeats the winning one once with the pores that
  each template was described from: the probe's from this run's detection,
  and the stored capture's from this run's preparation, its Pore SIFT
  template (H39, H42), or the pinned detector on that capture. The engine
  scores with the unchanged `batched_scores`, recomputes the counted rows
  with the same operations for that one reference, and maps the rows to
  pores by running the research's `image_patches` on an image of pixel
  positions. The pair count must equal the score, the described pores must
  match the template rows, and the repeated score must equal the deciding
  score. Otherwise the run fails before saving, as in H43.
- The server validates the pairs as in H43 and sends the illustration with
  the committed result, for matches and non-matches. The client names
  pores or points by method and adds one sentence with the method's
  counting rule, OpenCV SIFT's RANSAC requirement included.

Validation reproduced all 435 second-set H10 scores for both pore methods
with the illustration requested. Every pair count equalled its score, and
every coordinate lay on a native pore of its template: 10,087 Pore SIFT
pairs and 9,128 learned pairs. The full server run passed 211 tests,
including the four local checks with stored captures. All 15 engine tests,
including the real pore engines on synthetic images, 109 client tests, type
checks and the build passed. The built client passed 71 offscreen checks
with real engines and stored captures, including both pore illustrations
and the Hebrew page. Manual scanner validation follows separately.

## 2026-11-08: live pore match illustration check

The Pore SIFT and learned pore 1:1 match illustrations (H44) passed a
manual check on the connected HiScan PRO.

## 2026-11-08: 1:N match illustration of the caller's own print

Approved on 2026-11-08. Draw a 1:N result's matches for the caller's own
print only, completing the match drawings of increment 3 (H18, H41, H42).

- **H45** The illustrated candidate is the caller's highest-ranked own
  enrolment among the five shown candidates. Another user's capture is never
  opened for presentation or sent; when no own print is shown, the page says
  that there is no drawing and why.
- The search records each enrolment's earliest highest-scoring placement.
  After ranking, the server repeats that one comparison with `view = true`,
  for all three methods, and requires the repeated score to equal the
  ranked score. For the learned descriptor it supplies the pores both
  templates were described from, as H44 does: the probe's detection in this
  run, and for the stored capture this run's preparation of the caller's own
  captures, its Pore SIFT template, or the pinned detector. Pairs are
  validated as in H43. A failure ends the run before saving.
- The result carries the illustration with its rank, finger and placement,
  sent with the committed attempt. The page names the finger and rank above
  the H43/H44 drawing, which keeps the method's counting rule. The search,
  ranking, anonymity and attempt retention of H41 and H42 are unchanged; the
  processing time still ends after the ranking.

The full server run passed 217 tests, including the four local checks with
stored captures. All 112 client tests, type checks and the build passed.
The built client passed 71 offscreen checks with the real OpenCV SIFT engine
in a two-account gallery of stored captures: the caller's leading print is
drawn, and when the other account leads, only the caller's own print at
rank 2 is drawn. Manual scanner validation follows separately.

## 2026-11-09: live 1:N match illustration check

The 1:N match illustration of the caller's own print (H45) passed a manual
check on the connected HiScan PRO. Increment 3 is complete: all three
fingerprint methods in 1:1 and 1:N, with their match drawings (H20).

## 2026-11-09: Pore CNN as the display name of the learned pore descriptor

Approved on 2026-11-09. Call the research's learned pore descriptor "Pore
CNN" in every text that people read, in both interface languages (H2, H6).

- **H46** The name states what distinguishes the method. It uses the same
  detected pores as Pore SIFT, and a small convolutional neural network
  trained in the research describes the window around each pore, where Pore
  SIFT uses SIFT. Like OpenCV SIFT and Pore SIFT, it reads the same in
  English and Hebrew.
- Earlier records keep their wording: "learned pore descriptor", "learned
  descriptor" and "second trained pore descriptor" in H6 to H45 name the
  same method.
- Identifiers do not change. The code `learned-pore` is stored in every
  template and attempt row and bound into the encryption of stored
  templates, and engine and test file names keep it. The research's code,
  the labels its results pages generate and its method document's file name
  also stay: a research change outside README.md and docs/ would be a new
  research version (H21).

## 2026-11-09: copyright notice and an independent archive

Approved on 2026-11-09. State the rights in both repositories explicitly,
and keep a dated copy of each outside GitHub.

- **H47** Both repositories stay public, so that the work can be read,
  evaluated and cited. Their code and documentation are under copyright, all
  rights reserved: any use, copying, modification or distribution needs prior
  written permission. Neither repository had a license before, so the same
  default applied without being stated.
- This repository has a `LICENSE` file with that text, a License section in
  the README and a `CITATION.cff` file for citing. The client's
  `package.json` already declared `UNLICENSED`. Third-party software, models
  and data keep their own licenses and terms.
- The research repository states the same in its README only. A license
  file in its root would be a research change outside README.md and docs/,
  that is, a new research version (H21); the pin stays at 606c8d3.
- After the push, each repository is saved once to Software Heritage, the
  public archive of source code, as a dated copy held by a third party. The
  archive keeps what it saves permanently, which suits repositories that stay
  public.

## 2026-11-09: face enrolment from the PC's cameras

Approved on 2026-11-09. Enrol the face from the PC's own cameras, the first
step of increment 4 (H17, H20); verification, identification and the files of
H27 follow as steps of their own.

- **H48** The face engine runs in a new environment, `multimodal-face`, from
  conda-forge: Python 3.12.16, numpy 2.5.4 and OpenCV 5.0.0 without its GUI,
  each the newest version published at least 14 days earlier (H23). YuNet
  (MIT) finds faces and SFace (Apache 2.0) describes one. Both come from OpenCV
  Zoo and are pinned by SHA-256 (`engines/README.md`); SFace's embedding of 128
  values is read from the model.
- The page owns the camera. Its live view is mirrored and sends a 320-pixel
  copy of a frame about five times a second, so the face box it draws comes
  from the detector that decides; frames are never stored. A taken image is
  the camera's frame as a PNG. It must have exactly one face with YuNet's score
  of at least 0.9 (its demo's threshold), wholly inside the image and at least
  112 pixels wide (SFace's input, so no face is enlarged). No standard face
  quality score is used in this step.
- As H15 does for fingerprints, the enrolment keeps three images whose three
  pairs are all above SFace's threshold of 0.363, and another image is taken
  until six pass or twelve are taken. Every face score is pgvector's cosine
  similarity, the computation that 1:1 and 1:N will use. The images are sealed
  with their checks in `sample.checks`; the embeddings are unsealed `vector`
  values under the model's SHA-256 (H14). The server keeps nothing between
  requests and checks every image again before it saves. A new enrolment
  replaces the current one, and the face's enrolments can be deleted, as H34
  does for a finger. Migration `biometric_0005` adds SFace's row.
- The client chooses the camera itself. A camera is known by the USB model in
  its label, so a choice survives another port; the built-in camera is the one
  that faces the user (Windows' panel location). With the laptop's lid closed
  Windows turns the built-in screen off, which the main process reports; the
  built-in camera, still listed and sending a flat dark picture, is then tried
  last, and a second of flat frames marks any camera as covered. Cameras
  plugged in or out are followed at once. The order is the user's last choice,
  then a USB camera, then the built-in one; a selector appears when more than
  one camera can be used. Both are asked for 1280 x 720 at 30 frames a second.
  The camera is granted to the app's own page, for video only.

Checked on 2026-11-09 with the laptop's lid closed: the USB camera (a
Microsoft LifeCam HD-3000) gave 1280 x 720 at 30 frames a second; the
built-in camera, which reaches 2560 x 1440, opened but sent a flat picture
(a luma spread of 1.2, against 51 to 72 for a room), and Windows reported
only the two external monitors. OpenCV 5.0.0 ran both models: YuNet found
one face on the USB camera, at a score of 0.928 and 223 pixels wide, and
SFace returned 128 values. The full server run passed 237 tests, including
the four local checks with stored captures; all 126 client tests, type checks
and the build passed, and 21 engine tests. The built client passed 78
offscreen checks with the real face engine and Chromium's synthetic camera,
in both languages and themes. Enrolment of a real face is checked by hand on
both cameras.

## 2026-11-09: live face enrolment check

The face enrolment (H48) passed a manual check on the researcher's PC. The
local database holds one face enrolment with three sealed 1280 x 720 images
of about 1 MB each, every check passed (YuNet scores of 0.945 to 0.948, faces
230 to 235 pixels wide), and three SFace embeddings of 128 values under the
pinned model's SHA-256.

## 2026-11-09: face verification

Approved on 2026-11-09. Verify the face with one image from the PC's cameras,
the second step of increment 4 (H15, H20), as H35 does for a finger.

- **H49** After SFace's card, without a choice, and an explicit start (H40),
  the camera of H48 takes one image that must pass H48's four checks; a
  rejected image is taken again and makes no attempt, at most twelve per run.
  In one SQL statement, pgvector's cosine similarity compares it with the
  user's three current embeddings; the highest decides, strictly above 0.363,
  and equal scores go to the earliest image (H43). Templates of another model
  version are refused.
- Every completed comparison, match or not, is saved as H35's attempt:
  `face`, `verify`, `sface`, the enrolment compared, the score and the
  threshold used, the decision, the time from the image's receipt through
  the comparisons, `source = device`, and the image sealed under
  `mbs/probe/v1`. It is saved while the enrolment is locked and still
  current; a new enrolment or a deletion meanwhile ends the run unsaved.
  The answer is sent only after the save. Deleting the face erases its
  verification attempts; a new enrolment keeps the earlier ones.
- The result shows the new aligned face beside the closest enrolled one, the
  similarity with its threshold, the decision, the time and all three scores.
  The winning stored image is opened for its owner only and extracted again,
  and its embedding must equal the stored one; SFace gave the same 128 values
  in five repeats and in two processes. Otherwise the run ends unsaved.

The full server run passed 247 tests, including the four local checks with
stored captures; all 130 client tests, type checks and the build passed. The
built client passed 79 offscreen checks, among them verification before an
enrolment, which offers the enrolment first. Verification of a real face is
checked by hand.

## 2026-11-09: live face verification check

Face verification (H49) passed a manual check on the researcher's PC: six
attempts, all matches, with similarities of 0.570 to 0.894 against the
threshold of 0.363 and 66 to 83 ms of processing, each saved with its image
sealed (about 1 MB).

## 2026-11-09: face identification

Approved on 2026-11-09. Identify the face with one image from the PC's
cameras, the third step of increment 4 (H15, H20), as H41 does for a finger.

- **H50** After SFace's card, without a choice, and an explicit start (H40),
  the camera of H48 takes one image that must pass H48's four checks; a
  rejected image is taken again and makes no attempt, at most twelve per run.
  Without the caller's own face enrolment, the message of H15 is shown.
- The gallery is the current face enrolments of the active user accounts,
  found through their sealed identity links, each with three SFace embeddings
  of the pinned model; it and the threshold are fixed when the image arrives.
  One SQL statement ranks the enrolments by their highest pgvector cosine
  similarity, an exact search without an index. The leader is found only
  strictly above the threshold, and equal leaders are ordered by enrolment
  identifier and reported as a tie. Before the save, the accounts, then the
  enrolments and their templates are locked and checked again; a deletion, a
  new enrolment, a disabled account or a changed template ends the search
  unsaved.
- Every completed search, found or not, is saved as H41's attempt: `face`,
  `identify`, `sface`, the leading enrolment even below the threshold, the
  number of embeddings searched, the score and the threshold used, the
  decision, the time from the image's receipt through every comparison,
  `source = device`, and the image sealed under `mbs/probe/v1`. The answer is
  sent only after the save. Deleting a face keeps the identification attempts
  that it led, with their link emptied (H41), and erases its verification
  attempts (H49); the confirmation says both.
- The result shows the five leading enrolments with their similarities. The
  caller's own enrolment is named; the others are "another registered user",
  without a picture, a name or an identifier (H18). When the caller's
  enrolment is among the five, its winning image is extracted again as in H49
  and its aligned face is shown beside the new one; otherwise the page says
  why no face is shown. The gallery's size and the processing time follow.
- The search takes a few milliseconds, so the specification's pass over the
  gallery plays once, for about 0.6 s, when the answer arrives; the time
  shown stays the server's processing time, and the pass is skipped when
  Windows' animation effects are off.

The full server run passed 265 tests, including the four local checks with
stored captures; all 137 client tests, type checks and the build passed. The
built client passed 81 offscreen checks, among them identification before an
enrolment, which offers the enrolment first. Identification of real faces is
checked by hand.

## 2026-11-10: live face identification check

Face identification (H50) passed a manual check on the researcher's PC with
two accounts, the second enrolled for this check: four searches, all found,
each led by the caller's own enrolment, with similarities of 0.607 to 0.884
against the threshold of 0.363 and 62 to 123 ms of processing, over
galleries of three and six embeddings, each saved with its image sealed
(about 0.77 MB).

## 2026-11-10: face images from files

Approved on 2026-11-10. Let an image file take the camera's place in face
verification and identification, the fourth and last step of increment 4,
within H27 (H20, H49, H50).

- **H51** The file stays out of sight. On the 1:1 and 1:N camera screens
  only, also when no camera is connected, a small "more options" button
  beside the camera opens a menu with one item that takes a file, with a line
  saying that an image can also be dragged onto the window; a file dragged
  over the window shows the drop target only while it is dragged. Enrolment
  offers neither. One file at a time; the page checks only its size and sends
  its content alone, never its name, and a file counts toward the twelve
  images of a run.
- The two routes take the image's source, `device` (up to 8 MB) or `file`
  (up to 10 MB). Before the engine reads a file, the server takes its kind
  from its first bytes (JPEG or PNG, nothing else) and its width and height
  from its header: at least 240 pixels on the shorter side and at most 50
  million pixels. A file that fails is answered as a rejected image with its
  checks and makes no attempt; the face checks of H48 follow for a file that
  passes.
- The face engine sets OpenCV's own limit of 50 million pixels before OpenCV
  loads, so a small file that would decode to more is refused before any
  memory is taken for it, and it reports that as an unreadable image. OpenCV
  turns a photo upright by its EXIF orientation as it decodes. An image whose
  longer side is above 1920 pixels is scaled down to 1920, never up, and the
  detection, the alignment, the embedding and the stored image all use that
  copy, so the stored image is the one compared. The camera's images are
  unchanged, and the replies give the size as decoded and as used.
- The attempt records `source = file` and keeps the scaled copy's pixels as
  PNG, sealed as before; the original file, its name and its metadata are not
  kept. Both result screens name the source and, for a file, its size.

Checked on 2026-11-10 with OpenCV 5.0.0 on synthetic images only: a JPEG
with EXIF orientation 6 was decoded upright; a 0.17 MB PNG of 56 million
pixels was refused in 3 ms instead of being decoded to 168 MB; a 24 million
pixel, 9.7 MB JPEG took 97 ms to decode and 13 ms to scale, YuNet took 50 ms
on the scaled copy against 485 ms at full size, and the copy's PNG was 3.7 MB.

The full server run passed 276 tests, including the four local checks with
stored captures; all 24 engine tests, 142 client tests, type checks and the
build passed. The built client passed 86 offscreen checks with the real face
engine: with an enrolment of synthetic numbers, the menu stays closed until
it is opened, a dragged file shows the drop target, a dropped image without a
face is refused with its checks, 1:N offers the same menu and enrolment none.
Images of real faces from files are checked by hand.

## 2026-11-10: large and small faces

Approved on 2026-11-10. The manual check of H51 found a clear 1080 x 1080
photo in which no face was found: YuNet detects faces of "around 10x10 to
300x300" pixels (OpenCV Zoo's model notes), and that face was about 430 x 595.
Faces are now found at every size from 112 pixels wide to the whole frame,
and compared on the image's own pixels (H48, H51).

- **H52** A face is detected on the image, or on its copy of 1920 pixels
  (H51), at its own size, as before. Only when none is found there, the face
  engine detects again on smaller copies, whose longer side is 960, 640, 480
  and 320 pixels, and stops at the first copy with a face.
- A face found on a smaller copy, or on a copy smaller than the image, is
  found again on the image's own pixels: the region around it is cut from the
  image and scaled so that the face is about 200 pixels wide, never enlarged,
  and detected once more. Its box and landmarks are given in the image's own
  pixels, and the checks of H48 (inside the image, at least 112 pixels wide),
  the alignment and the embedding use the image's own pixels. A face under 112
  pixels wide in the image itself is still refused: SFace's input is 112 x 112,
  and an enlarged face would cost accuracy.
- An image whose face is found at its own size and that is not larger than
  1920 pixels is read exactly as before, which holds for every camera frame and
  every stored enrolment, so H49's repeated extraction is unaffected. A file
  larger than 1920 pixels is still stored as its copy of 1920 (H51), so its
  stored image is a smaller copy of the compared one; the result names both
  sizes.

Measured on 2026-11-10 on the researcher's photo, in memory only: the face was
found on the copy of 640 pixels and again on the photo's own pixels at a score
of 0.942; landmarks mapped back from the copy alone differed by up to 10.7
pixels, and their embedding was only 0.961 like the one from the landmarks
found again, which is why the face is found again before alignment. The same
photo made small inside a grey 6000 x 4000 frame gave a face 71 pixels wide on
the 1920 copy, refused before H52, and 234 pixels wide on the frame's own
pixels, with an embedding 0.975 like the close photo's.

The full server run passed 276 tests, including the four local checks with
stored captures; all 27 engine tests, three of them new with a stand-in
detector, 142 client tests, type checks and the build passed, and the built
client passed 86 offscreen checks. Faces of every size from files are checked
by hand.

## 2026-11-10: live check of face images from files

Face images from files (H51) and faces of every size (H52) passed a manual
check on the researcher's PC: 31 verifications and 2 identifications from
files, each saved with `source = file` and its image sealed (0.23 to 5.2 MB),
in 16 to 239 ms of processing. Sixteen verifications matched, with
similarities of 0.386 to 0.751 against the threshold of 0.363, and fifteen
did not (0.019 to 0.362); one identification found the leading enrolment at
0.431, and one found none. The close photo of H52, refused before that
decision, matched. Increment 4 is complete: the face from the PC's cameras
and from files, in enrolment, 1:1 and 1:N (H20).

## 2026-11-10: a choice between the camera and an existing image

Approved on 2026-11-10. Separate the face's live capture from the upload of
an existing image, and end every attempt with a way back to that choice
(H27, H40, H49 to H51).

- **H53** After "Verify my face (1:1)" or "Identify (1:N)", SFace's card
  offers two choices in place of the start button: "Live verification" or
  "Live identification", which opens the camera, still only on this explicit
  choice (H40), and "Upload an existing image", a screen of its own with a
  visible drop zone and a button that chooses a file. The camera screen takes
  no file. For the face this replaces the hidden menu of H27 and H51 with a
  visible, secondary choice; enrolment still takes its images from the camera
  only.
- Every attempt ends on an outcome screen: the result of H49 or H50, a refused
  image or file with its checks, or a failure. Each offers "Verify again" or
  "Identify again", which returns to the choice, and "Back". A refused image
  no longer leaves the camera open for another take, so a run takes one image
  and the twelve images of a run no longer apply.
- The server, the checks of H48 and H51 and the stored attempts are unchanged.

All 142 client tests, type checks and the build passed, and the built client
passed 89 offscreen checks: verification and identification open on the
choice without a camera, the camera screen takes no file, the file screen
shows its drop zone, a dropped image without a face ends on its outcome screen
whose "Verify again" returns to the choice, and enrolment offers no file. The
server is unchanged since its 276 tests passed for H52.

## 2026-11-10: live check of the choice between the camera and an existing image

The choice of H53 passed a manual check on the researcher's PC: live and
uploaded images in verification and identification, refused images on their
outcome screen, and "again" returning to the choice.

## 2026-11-11: voice enrolment from the PC's microphones

Approved on 2026-11-11. Enrol the voice from the PC's own microphones, the first step of increment 5 (H17,
H20); verification, identification and the recordings from files of H27 follow as steps of their own.

- **H54** The voice engine runs in a new environment, `multimodal-voice`. From conda-forge come Python
  3.12.16, PyTorch 2.13.0 for the CPU, torchaudio 2.11.0, libsndfile 1.2.2 and the packages SpeechBrain
  needs, each the newest version published at least 14 days earlier that works with the others (H23):
  torchaudio's builds of that age are made for PyTorch 2.13, and conda-forge's torchaudio brings kaldi and
  torchcodec, pinned to CPU builds. SpeechBrain 1.1.2 and HyperPyYAML 1.2.3 are not on conda-forge; they come
  from PyPI, pinned by SHA-256 and installed without dependencies (`environments/voice-pip.txt`).
- The model is SpeechBrain's ECAPA-TDNN, `speechbrain/spkrec-ecapa-voxceleb` (Apache 2.0), at a pinned Hugging
  Face commit. Its five files are pinned by SHA-256 (`engines/README.md`) and loaded with SpeechBrain's own
  interface from their folder, without the network. The embedding of 192 values is read from the model and
  computed as SpeechBrain's verification does; the engine always uses eight threads, since PyTorch gives
  exactly the same values in every run only with the same number of threads.
- The page owns the microphone, and the client chooses it: the user's last choice, then a camera's own
  microphone (one device group in Chromium), then Windows' default microphone, then the others, USB ones
  first. A microphone that sends nothing but digital silence is passed over, and a selector appears when more
  than one can be used. The microphone is granted to the app's own page, for audio only, never with the camera
  in one request, and its sound is taken as it is, without the browser's echo cancellation, noise suppression
  and automatic gain. Each recording lasts five seconds and starts on an explicit "Record"; a sentence of about
  four seconds is shown in the interface's language, a different one each time, with a level meter and a
  timer. The page sends the recording as a WAV of 16 kHz, one channel and 16-bit PCM.
- A recording must be 3 to 30 seconds long, hold at least two seconds of speech that stands at least 15 dB
  above the room's noise (the level of its quietest tenth, in windows of 25 ms every 10 ms, with pauses of up
  to 0.2 s counted as speech), and have at most 0.1 % of its samples at the 16-bit limits. No standard voice
  quality score is used in this step.
- As H48 does for the face, the enrolment keeps three recordings whose three pairs are all above SpeechBrain's
  threshold of 0.25, by pgvector's cosine similarity, and another recording is made until six pass or twelve
  are made. The recordings are sealed as WAV made by the engine from their samples, with their checks in
  `sample.checks`; the embeddings are unsealed `vector` values under the embedding model's SHA-256 (H14). The
  server keeps nothing between requests and checks every recording again before it saves. A new enrolment
  replaces the current one, and the voice's enrolments can be deleted. Migration `biometric_0006` adds the
  model's row.

Checked on 2026-11-11, without recording anyone. Chromium names the LifeCam's microphone with its model
(045e:0779) and gives it the LifeCam camera's device group; Windows' default microphone on the researcher's PC
was a USB audio adapter (1b3f:2008), and the laptop's own microphone array has no model; all three deliver 48
kHz. SpeechBrain 1.1.2 loaded the model from its folder without the network and without linking or copying a
file; a five-second recording took 80 to 150 ms with 24 and 8 threads, and its 192 values were the same in
every repeat and in another process with the same number of threads, while 1, 8 and 12 threads each gave
values slightly unlike those of 2, 4, 6, 16 and 24.

The full server run passed 297 tests, including the four local checks with stored captures; all 37 engine
tests (ten of them for the voice, on synthetic recordings), 160 client tests, type checks and the build
passed. The built client passed 63 offscreen checks with the real face and voice engines and Chromium's
synthetic microphone, playing a synthetic recording of tones in bursts, never a person's voice: three of its
recordings passed the checks (4.0 seconds of speech, 35 dB above the noise) and matched each other at 0.94 to
0.97, so the synthetic voice was enrolled, shown and deleted again. Enrolment of a real voice is checked by
hand.

## 2026-11-11: live voice enrolment check

Voice enrolment (H54) passed a manual check on the researcher's PC. The local database holds one voice
enrolment with three sealed five-second recordings of about 160 KB each, every check passed (3.05 to 3.64
seconds of speech, 21 to 23 dB above the room's noise, no clipped samples), and three ECAPA-TDNN embeddings of
192 values under the pinned model's SHA-256; their three pairs are 0.795 to 0.810 alike, against the threshold
of 0.25.

## 2026-11-11: voice verification

Approved on 2026-11-11. Verify the voice with one recording from the PC's microphones, the second step of
increment 5 (H15, H20), as H49 does for the face.

- **H55** "Verify my voice (1:1)" leads, without a voice enrolment, to the message of H15; with one, to
  ECAPA-TDNN's card, which offers "Live verification" and "Back" as H53 does for the face (an existing recording
  joins this choice with the files of H27). The microphone of H54 opens only on that choice (H40), and one
  recording of five seconds, reading the last of the sentences, must pass H54's checks; a refused recording
  makes no attempt.
- In one SQL statement, pgvector's cosine similarity compares it with the user's three current embeddings; the
  highest decides, strictly above 0.25, and equal scores go to the earliest recording (H43). Templates of
  another model version are refused. The winning stored recording is opened for its owner only and described
  again, and its embedding must equal the stored one, which the engine's fixed number of threads makes exact;
  otherwise the run ends unsaved.
- Every completed comparison, match or not, is saved as H49's attempt: `voice`, `verify`, `ecapa-voxceleb`,
  the enrolment compared, the score and the threshold used, the decision, the time from the recording's
  receipt through the comparisons, `source = device`, and the engine's WAV of the recording sealed under
  `mbs/probe/v1`. It is saved while the enrolment is locked and still current, and the answer is sent only after
  the save. Deleting the voice erases its verification attempts; a new enrolment keeps the earlier ones.
- Every attempt ends on an outcome screen, as H53 has it: the result, a refused recording with its checks, or a
  failure, each with "Verify again", which returns to the choice, and "Back". The result shows the decision, the
  new recording beside the closest enrolled one, each as a waveform that can be played, the similarity against
  the threshold, the time and all three scores.

The full server run passed 307 tests, including the four local checks with stored captures; all 166 client
tests, type checks and the build passed, and the 37 engine tests are unchanged. The built client passed 67
offscreen checks: the synthetic voice of H54's check, enrolled through the real engine, was verified with a
recording of the same synthetic microphone at 0.954 to 0.996, and "Verify again" returned to the choice.
Verification of a real voice is checked by hand.

## 2026-11-12: live voice verification check

Voice verification (H55) passed a manual check on the researcher's PC: the local database holds one voice
verification attempt, a match with a similarity of 0.749 against the threshold of 0.25 and 127 ms of processing,
saved against the current enrolment with its recording sealed (about 160 KB). A refused recording makes no
attempt, so the database does not show whether one was tried.

## 2026-11-12: voice identification

Approved on 2026-11-12. Identify the voice with one recording from the PC's microphones, the third step of increment 5
(H15, H20), as H50 does for the face.

- **H56** "Identify (1:N)" leads, without a voice enrolment, to the message of H15; with one, to ECAPA-TDNN's card,
  which offers "Live identification" and "Back" as H55 does for verification. The microphone of H54 opens only on that
  choice (H40), and one recording of five seconds, reading the last of the sentences, must pass H54's checks; a
  refused recording makes no attempt and ends on its outcome screen.
- The gallery is the current voice enrolments of the active user accounts, found through their sealed identity links,
  each with three ECAPA-TDNN embeddings of the pinned model; it and the threshold are fixed when the recording
  arrives. One SQL statement ranks the enrolments by their highest pgvector cosine similarity, an exact search without
  an index. The leader is found only strictly above 0.25, and equal leaders are ordered by enrolment identifier and
  reported as a tie. Before the save, the accounts, then the enrolments and their templates are locked and checked
  again; a deletion, a new enrolment, a disabled account or a changed template ends the search unsaved. The gallery,
  the ranking and the locked save are now one implementation for the face and the voice, given the modality and its
  model, and the face's behaviour is unchanged.
- Every completed search, found or not, is saved as H50's attempt: `voice`, `identify`, `ecapa-voxceleb`, the leading
  enrolment even below the threshold, the number of embeddings searched, the score and the threshold used, the
  decision, the time from the recording's receipt through every comparison, `source = device`, and the engine's WAV of
  the recording sealed under `mbs/probe/v1`. The answer is sent only after the save. Deleting a voice keeps the
  identification attempts that it led, with their link emptied (H41), and erases its verification attempts (H55); the
  confirmation says both.
- The result shows the five leading enrolments with their similarities. The caller's own enrolment is named; the
  others are "another registered user", without a recording, a name or an identifier (H18). When the caller's
  enrolment is among the five, its winning recording is described again as in H55 and shown beside the new one, each
  as a waveform that can be played; otherwise the page says why no recording is shown. The pass over the gallery of
  H50 plays once when the answer arrives; the gallery's size, the processing time and the source follow, and
  "Identify again" returns to the choice.

The full server run passed 326 tests, including the four local checks with stored captures and the face's 18
identification tests, unchanged; all 175 client tests, type checks and the build passed, and the 37 engine tests are
unchanged. The built client passed 72 offscreen checks: the synthetic voice of H54's check, enrolled through the real
engine, was identified from a recording of the same synthetic microphone at 0.982, its own enrolment first and its
closest recording beside the new one, and "Identify again" returned to the choice. Identification of real voices is
checked by hand.

## 2026-11-12: live voice identification check

Voice identification (H56) passed a manual check on the researcher's PC with two accounts, the second enrolled for this
check: the local database holds two voice identifications, both made from the second account over a gallery of six
embeddings (two enrolments), both found, with similarities of 0.789 and 0.733 against the threshold of 0.25 and 81 and
78 ms of processing; the first was led by the other account's enrolment and the second by the caller's own, each saved
with its recording sealed (about 160 KB). A refused recording makes no attempt, so the database does not show whether
one was tried.

## 2026-11-12: two corrections of voice verification

Approved on 2026-11-12, found while H56 was built; no decision changed (H15, H55).

- On the live screen of voice verification, the empty status line under the microphone showed as a tinted strip, 18
  pixels high, until the comparison started; it now takes no room, as on the enrolment's and identification's screens.
- Before a voice enrolment, the "Home" of H15's message returned to the voice page; it now returns to the home screen,
  as H15 says and the face's messages do. Verification and identification share that message.

All 175 client tests, one of them extended, type checks and the build passed, and the built client passed 74 offscreen
checks, two of them new: they measure the empty status line of live verification (18 pixels high before the
correction, none after) and of live identification. The server is unchanged.

## 2026-11-12: voice recordings from files

Approved on 2026-11-12. Let a recording file take the microphone's place in voice verification and identification, the
fourth and last step of increment 5, within H27 (H20, H53, H55, H56).

- **H57** ECAPA-TDNN's card in 1:1 and 1:N offers "Upload an existing recording" beside the live choice and "Back", as
  H53 does for the face: a screen of its own with a visible drop zone, a button that chooses a file and the rules. The
  microphone does not open there, and enrolment still takes its recordings from the microphone only. One file at a
  time; the page checks only its size, up to 10 MB, and sends its content alone, never its name.
- Both routes take the recording's source, `device` (up to 1 MB, as before) or `file` (up to 10 MB). The server takes
  a file's kind from its first bytes: a WAV, an OGG or an MP3 (an ID3 tag or an MPEG frame of Layer III); any other
  file is answered as a refused recording with its check and makes no attempt.
- The voice engine reads the file's header with libsndfile, from memory, before anything is decoded: a WAV (any
  encoding libsndfile reads, the extended WAV included), an OGG of Vorbis or Opus, or an MP3; a sample rate of 16 to
  192 kHz, since resampling cannot add the band that a slower recording lacks (SpeechBrain's own note) and the upper
  bound keeps a header from asking for an unbounded read; one or two channels; and 3 seconds to two minutes, which
  replaces H27's thirty seconds. Only a file within these limits is decoded, then converted as SpeechBrain's own `load_audio` converts a file (torchaudio's sinc
  resampler takes every channel to 16 kHz, then the channels are averaged) and made 16-bit PCM. The checks of H54 and
  ECAPA-TDNN then run on that recording exactly as on one from the microphone.
- The attempt records `source = file`, and its sealed probe is the engine's WAV of the converted recording, so the
  recording stored is the one compared; the original file, its name and its metadata are not kept. The answer adds
  what was read from the header and the converted recording, the caller's own, so the result shows and plays it
  beside the enrolled one and names its source; a refused file ends on the outcome screen with its checks.

ECAPA-TDNN describes a recording whole, and its time and memory grow with the length. Measured on 2026-11-12 in the
engine, on synthetic signals, the time and the process's peak memory were 0.8 s and 0.9 GB at thirty seconds, 1.8 s
and 2.3 GB at two minutes, 3.9 s and 5.5 GB at five minutes, and 7.8 s and 9.9 GB at ten, on a PC of 31.4 GB with
11.5 GB free at the time; the synthetic voice gave 0.988 to 0.990 alike embeddings at every length. Thirty seconds was
a cautious bound rather than a need of the model, so a file is compared whole up to two minutes, and a longer one is
refused by its header. The limit of 10 MB of H27 stays: a WAV of 48 kHz and two channels reaches it after about 55
seconds, an MP3 or OGG of two minutes takes 1 to 2 MB.

Checked on 2026-11-12 with synthetic signals only, in the voice environment: its libsndfile 1.2.2 is built with
mpg123, LAME, libvorbis and libopus and reads WAV, OGG and MP3 from memory, so no download was needed. The header gave
the rate, the channels and the length in under a millisecond, and an MP3 of 3.3 MB held 600 seconds, which is why the
length is read before decoding. Against a lossless WAV of the same signal, ECAPA-TDNN found the MP3 0.996 to 0.999
alike, the Vorbis 0.980 to 0.994 and the Opus 0.997; an 8 kHz copy brought back to 16 kHz was only 0.907 alike its 16
kHz original. A 30-second MP3 of 44.1 kHz and two channels was decoded in 33 ms and converted in 18 ms. Writing the
test files showed two faults of libsndfile's encoders, which the system never uses: its MP3 encoder garbled 16-bit
stereo samples and its Vorbis encoder overflowed the stack on twelve seconds in one call, so the tests write floats in
blocks.

The full server run passed 341 tests, including the four local checks with stored captures; all 39
engine tests, among them two new ones in which every format is converted exactly as SpeechBrain's `load_audio` converts
it, 179 client tests, type checks and the build passed. The built client passed 78 offscreen checks with the real
engines: the synthetic voice of H54's check, as an MP3 of 44.1 kHz and two channels, was verified at 0.958 and
identified with its own enrolment first, and an 8 kHz copy was refused by its header. Recordings of a real voice from
files are checked by hand.

## 2026-11-12: live check of voice recordings from files

Voice recordings from files (H57) passed a manual check on the researcher's PC: the local database holds four attempts
from files, all made from his own account and all matches. Three are verifications: a recording of about 18 seconds,
twice, at a similarity of 0.690 in 212 and 292 ms, and one of about 35 seconds, longer than the thirty seconds that
H57 replaced, at 0.283 in 491 ms; the fourth identified that second recording, led by his own enrolment among two, at
0.283 in 454 ms. Each was saved with `source = file` and its converted recording sealed (about 0.58 and 1.12 MB). The
files' formats are not kept, and a refused file makes no attempt, so the database does not show which formats or which
refused files were tried. Increment 5 is complete: the voice from the PC's microphones and from files, in enrolment,
1:1 and 1:N (H20).

## 2026-11-13: corrections of the documents before increment 6

Approved on 2026-11-13, from a reading of the documents against the code before increment 6; no decision changed (H20,
H26, H31).

- `README.md` listed fusion among the fingerprint methods, in its highlights and in its table of modalities. Fusion
  belongs to increment 6 and is not built, so both now say that it follows in increment 6. Its list of folders named
  only the fingerprint engines under `engines/`; it now names the face and voice engines too (H48, H54).
- `client/package.json` described "The Hebrew desktop client"; the client is in English or Hebrew (H31).
- Section 3 of the specification said in the present tense that the client starts and stops the server. H26 left that
  to a later step, and the server is still started on its own; the section now says so.
- Section 9 of the specification named "the Hebrew client shell" in increment 1; it now names both languages (H31).

The README's screenshots are still the design prototypes of October, among them one that shows Pore CNN under its
earlier name beside a fusion card; screenshots of the real client replace them when the final design is built (H35).
No code changed.

## 2026-11-14: a fingerprint enrolment ends with its page

Approved on 2026-11-14, from a reading of the code before increment 6; no decision changed (H33, H35, H41).

- Leaving the fingerprint screen already cancelled an enrolment, but reloading the page, or the page losing its
  process, did not. The client's main process kept the enrolment's request open, so the scanner went on waiting, up
  to 60 seconds for each placement, for an enrolment that no screen showed; a finger placed meanwhile still counted
  toward it, and every new capture was refused as busy until it ended. The main process now cancels an enrolment
  when its page reloads, loses its process or is closed, as H35 and H41 made it do for verification and
  identification, and the server stops the scanner as when the user cancels.
- The three streamed captures, enrolment, verification and identification, now share one implementation of that
  rule in the main process.

All 194 client tests passed, 15 of them new: each of the three captures is cancelled when its own page is closed,
starts loading again or loses its process, and not when another page does; its events reach only its page; and only
the window's top frame can start or cancel it. Against the previous main process the three enrolment cases failed and
the other twelve passed. Type checks and the build passed. The built client passed 68 offscreen checks with the real
NFIQ 2 and OpenCV SIFT engines and stored placements through a stand-in scanner: after a reload during an enrolment
that waited for a finger, the server closed the stand-in scanner 15 to 17 ms later in three runs, and an enrolment
started right after the reload completed. The server is unchanged. It passed a manual check on the HiScan PRO on
2026-11-14.

## 2026-11-14: corrections of the server's fingerprint code

Approved on 2026-11-14, from a reading of the code before increment 6; no decision changed (H10, H33, H35, H41).

- The enrolment's referee read OpenCV SIFT's score straight from the engine's reply, while verification and
  identification read it through one check (H10, H35). So a defined comparison failure reached the screen without a
  score, which it showed as zero, and a reply with an invalid score counted as a non-match while the enrolment went
  on. The referee now uses the same check: a defined failure scores zero, and an invalid reply ends the enrolment as
  the engine's failure, with nothing saved.
- Two names that other modules used from inside the fingerprint module are now public: the scanner's lock, which
  lets enrolment, verification and identification take the scanner one at a time, and the helper that writes data as
  Base64 text. The number of candidates a 1:N answer shows is defined once for fingerprints, faces and voices (H41,
  H50, H56), and the methods whose templates an enrolment makes besides OpenCV SIFT's (H38, H39) no longer carry a
  name from before increment 3.
- The server's own messages, which Python printed without their time, level or source and below WARNING not at all,
  now carry all three on standard error, from INFO up; uvicorn's own lines are unchanged.

All 344 server tests passed, three of them new, including the four local checks with stored captures and the real
engines. Against the previous code the two new tests of the referee failed: the failed pair had no score, and the
invalid reply let the enrolment go on until the stand-in scanner had no placement left. The client and the engines
are unchanged. It passed a manual check on the HiScan PRO on 2026-11-14.

## 2026-11-14: a message instead of an empty window

Approved on 2026-11-14, from a reading of the code before increment 6; no decision changed (H26, H31).

- A screen of the client that failed while it was drawn left the window empty until the page was reloaded. The
  client now shows a short message instead, in the screen's language (H31), with a way back to the main screen:
  inside the frame, which keeps its bar, and on the screens before sign-in. Any move to a screen, even the same one,
  shows it again, and React still reports the error to the client's console.

All 198 client tests passed, four of them new: a screen made to fail shows the message inside the frame, with its
bar, and before sign-in, in English and in Hebrew, and comes back after a move to it; without the change all four
failed, the window left empty. Type checks and the build passed, and the built client passed the offscreen checks
unchanged: 68 with the fingerprint engines and the 1:N gallery, and 78 with the face and voice engines. The server is
unchanged. It passed a manual check in the client on 2026-11-14.

## 2026-11-14: the local API answers only its own host names and bounded bodies

- **H58** Approved on 2026-11-14. Before any route runs, the server refuses a request whose Host header names
  anything but 127.0.0.1 or localhost, with 400 `invalid_host`, and a request body larger than its route takes, with
  413 `body_too_large`: 64 KiB for every route, except the nine face and voice routes that take images or recordings,
  whose limits are exactly what their models already allowed, with 1 KiB for the JSON around each image or recording
  (H48, H51, H54, H57). The body is checked by its declared length and again while it arrives, and is read into
  memory only within the limit; the route then gets exactly the body that was read. Each refusal is logged as a
  warning.

The server listens on 127.0.0.1 only (H11), yet a web page open in any browser on this PC can send it requests.
Through DNS rebinding such a page could reach the routes that need no sign-in (registration, sign-in, password
recovery) under a host name of its own, and any request could make the server read a body of any size before its
route refused it. The client addresses the server as 127.0.0.1 and checks the size of every file it sends, so nothing
changes for it. FastAPI 0.142.2 offers no body limit per route, and Starlette's own limit answers in plain text, so the
server has one small layer of its own (`server/mbs/guard.py`). The tests now address the server as 127.0.0.1, as the
client does.

All 350 server tests passed, six of them new, including the four local checks with stored captures: a request to
another host is refused while this PC's names pass with a port and in any case, a body one byte above its route's
limit is refused while the largest image file still reaches its route, a body without a declared length is counted
as it arrives, and every larger limit names a route of the API. Without the layer, the three of them that send
requests through the API failed. One earlier test now expects the new refusal: a live view frame of 2 MiB, which the
model refused before, is now refused before its route, while a frame a little longer than the model takes is still
refused by the model. The client and the engines are unchanged, and the built client passed its offscreen checks
against the guarded server without a refusal: 68 with the fingerprint engines and 78 with the face and voice engines,
images and recordings from files included. It passed a manual check on 2026-11-14.

## 2026-11-14: the API's routes by area

Approved on 2026-11-14, from a reading of the code before increment 6; no decision changed (H12, H58).

- `server/mbs/api.py` held all 33 routes inside one function of about 300 lines, with their request models and the
  policy, in a file of 532 lines, and increment 6 adds more. The routes now live by area in `server/mbs/routes/` (one's own account, fingerprints,
  faces, voices and the administration), each module with its request models, and read the databases, the keys and
  the services from the application's state. `api.py` only assembles them, with the guard (H58), the answers to
  refused requests and the health route. Who may call a route is still declared on it and checked on every request
  by one policy, the application's own dependency (H12).
- Behaviour is unchanged. A new test pins every route's path, method, name, status, roles and request model, the
  last by a short SHA-256 of its JSON schema; it passed against the previous code and passes now, and it checks that
  the policy is every route's first dependency. FastAPI 0.142.2 keeps the routes of included routers out of the
  application's route list until a request needs them, so the tests that list routes, among them the check that
  every route declares who may call it, now read them through FastAPI's own `iter_route_contexts`.

All 351 server tests passed, one of them new, including the four local checks with stored captures, and the built
client passed its offscreen checks against the new server unchanged: 68 with the fingerprint engines and 78 with the
face and voice engines. The client and the engines are unchanged. It passed a manual check on 2026-11-14.

## 2026-11-14: one implementation of the face's and the voice's flows

Approved on 2026-11-14, from a reading of the code before increment 6; no decision changed (H48 to H57).

- `server/mbs/face.py` and `server/mbs/voice.py` held the same enrolment and its save, deletion, verification and
  identification twice, apart from names, and copies drift apart, as two of the client's voice screens had before the
  corrections of 2026-11-12. The flows now live once in `server/mbs/embeddings.py`, next to the 1:N search they
  already shared (H56), with the modalities' common refusal and engine service. Each modality module describes itself
  in one object (its names, its rules and its own steps, such as how a finding is checked, what of it is sealed and
  what the result screen shows) and keeps what is truly its own: the engine's answers, the checks of an image, a
  recording or a file, and the face's live view. The functions the routes and the tests call keep their names.
- Behaviour is unchanged. The face's and the voice's tests passed without a change, among them the tests that replace
  a modality's extraction or repeated view meanwhile: the shared flows look those steps up in the modality's module
  at each call.

All 351 server tests passed, including the four local checks with stored captures, and the built client passed its
offscreen checks against the new server unchanged: 78 with the face and voice engines, in which a synthetic voice was
enrolled, verified and identified live and from an MP3 file, and deleted, through the real engine, and a synthetic
face enrolment was saved through the face's own save, and 68 with the fingerprint engines. The client and the engines
are unchanged. It passed a manual check on 2026-11-14.
