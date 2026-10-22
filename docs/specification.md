# System specification

Approved by the researcher on 2026-10-20 (H11–H20 in `docs/decisions.md`),
from the draft of 2026-10-19 as revised on 2026-10-20, and amended with his
approval since (H24–H26). Every decision is cited by its ID; a change needs
the researcher's approval and a new entry in the decision record.

## 1. Purpose and scope

The identification system of Stage B (H1): a user logs in with email or
username and password, then uses fingerprint (the primary modality), face and
voice, each with enrolment, 1:1 verification and 1:N identification. For each
modality the user chooses the algorithm from short descriptions of its
accuracy, speed and way of working, written for a simple but curious user;
the interface is in Hebrew, and verification and identification are built as
an impressive, interactive experience (H6).

Out of scope: liveness detection (H6), SD302 images in the system's databases
(H6), access from other machines or the internet, mobile devices.

One PC runs everything (H11): the researcher's PC with the HiScan PRO, its
integrated camera and its microphones (all present on 2026-10-19 and reported
OK by Windows; the camera and microphones are first tried in their
increments). The server listens on 127.0.0.1 only.

## 2. Accounts and roles (H12)

- **User account:** registered in the client with the national ID (H3); it
  signs in, enrols each modality, verifies (1:1) and identifies (1:N).
- **Administrator account:** separate and administrative only, with no
  national ID and no biometric data, so privileged work never runs from an
  everyday account (as NIST SP 800-53 AC-6(2) requires). It signs in on the
  same login screen and gets the administration area instead of the
  biometric screens (section 6).
- **Creating administrators:** the first one by a server command on the PC;
  further ones by an administrator in the client, with a one-time password
  that must be changed at the first sign-in.
- **Disabling:** an administrator can disable an account and enable it again;
  a disabled account cannot sign in and leaves the 1:N gallery. The last
  active administrator cannot be disabled.
- **Enforcement:** the server checks the role on every request and refuses
  whatever the role is not given (HTTP 403); the client only shows each role
  its own screens. The separation therefore holds even when someone calls the
  server directly.
- **Re-authentication and audit:** every administrative change (accounts,
  thresholds) asks for the administrator's password again and is written to
  an audit log (time, administrator, action, target) that the client can read
  but not change.

## 3. Architecture (H4)

```
Electron client: React + TypeScript, Hebrew, right to left
        │  HTTP and WebSocket on 127.0.0.1, session token
FastAPI server: Python 3.12, its own environment
        ├── accounts database (PostgreSQL): accounts, sessions, identity link, audit log
        ├── biometric database (PostgreSQL + pgvector): keyed only by random identifiers
        ├── scanner: ScannerCapture (C#, x86; OEM route H8, guided placements H9)
        └── engines, one process per method in its own environment (H4):
              fingerprint: OpenCV SIFT, Pore SIFT, learned pore descriptor
                           (research code through the pinned link, H10)
              face: YuNet detection + SFace recognition
              voice: SpeechBrain ECAPA-TDNN
```

- The client starts the local server when it opens and stops it when it
  closes. The server starts PostgreSQL under the user's own account when it
  is not running, so it needs no Windows service and no administrator rights
  (H19).
- The client's main process is its only network client and keeps the
  session token; the page, sandboxed and without Node.js, reaches it only
  through a preload bridge that offers a fixed list of routes (H26).
- WebSocket messages carry live progress during capture (scanner light on,
  placement kept, "lift the finger") and during 1:N searches.
- The engines are long-running child processes of the server (H13). Each
  message on their standard input and output is a JSON header followed by
  its binary data (images, templates), since one template can take several
  megabytes (5.1). An engine loads its models once and keeps no data between
  requests: the server sends the templates each request needs. For 1:N the
  CPU engines compare in parallel worker processes. Engines need only the
  standard library beyond their method, so the research environments get no
  new packages.
- A new acquisition mode of ScannerCapture returns the image and its checks
  to the server on standard output and writes no file, so a raw sample exists
  on disk only encrypted (H13). The OEM worker, its checks and the guided
  placements stay as they are.

## 4. Data and security (H3, H4, H14)

### Databases

| Database | Tables |
| --- | --- |
| accounts | account (username, email, password hash, role, status, theme (H24), created), national ID HMAC (unique; user accounts only), identity link (encrypted random identifier; user accounts only), session, audit log |
| biometric | subject (random identifier), algorithm (method, version, threshold), enrolment (subject, modality, finger position, created, replaced), sample (a finding: one encrypted raw capture), template (one per finding and method: encrypted for fingerprints, a vector for face and voice), attempt (section 7) |

The two databases share no key: only the encrypted identity link connects an
account to its subject, and rows of the biometric database name people only
by their subject identifiers. The exact tables, with every column, key and
encrypted value, are in `docs/data-model.md` (H25).

### Cryptography (the `cryptography` package for every primitive, H4)

- **National ID (H3):** checked with the Israeli ID check digit, then turned
  into HMAC-SHA256 under its own key for the duplicate check, so a second
  account with the same ID is refused. The number itself is never stored or
  logged.
- **Keys per record (H3, H14):** HKDF-SHA256 of the master secret with a
  random 32-byte salt per record and a label per use. The function is ours;
  the primitives are standard.
- **Encryption (H14):** AES-256-GCM for the identity link (a random 128-bit
  subject identifier), raw samples, the captures of attempts and fingerprint
  templates (templates are only read by the engines); an attempt's outcome
  stays unencrypted so that its history can be filtered (H25). Each
  ciphertext records the version of the key that sealed it, so keys can be
  replaced later, and is bound to its row as associated data, so it cannot
  be moved to another row; in the biometric database it is also bound to its
  subject, so it cannot be moved to another person (H25).
- **Passwords (H14):** Argon2id at RFC 9106's second recommended option (3
  passes, 4 lanes, 64 MiB, 128-bit salt, 256-bit tag); `cryptography`
  documents Argon2id from version 44.0.0 (checked on 2026-10-20; it is tried
  out when the server environment is built). Repeated failed sign-ins are
  slowed down.
- **Sessions (H14):** random tokens, stored only as their hashes, that expire
  after inactivity.
- **Face and voice embeddings (H4, H14):** pgvector columns, since pgvector
  cannot search encrypted vectors; like every template they are stored only
  under the subject identifier.
- **Keys (H3, H14):** outside the databases and the code, in a key file
  outside the repository that only the Windows user can read, loaded when the
  server starts. Without it the stored data can be neither read nor linked to
  its accounts, so the researcher keeps a backup copy of it.

Logs never contain national IDs, samples or templates.

## 5. Modalities

Verification and identification in a modality need the user's own enrolment
in it. Otherwise the system says that the modality is not available yet and
offers to enrol now or to return to the home screen (H15, the supervisor's
flow of 2026-10-18).

### 5.1 Fingerprint (primary)

- **Capture:** HiScan PRO at native 1000 ppi through the OEM route (H8), each
  image checked by H7's four checks. A run that fails with OEM status 110 (2
  of 32 runs in H9, each followed by a successful retry) is retried once.
- **Enrolment:** the user chooses the finger; it is captured in three
  separate placements, the finger lifted between them (H6, H9). Templates are
  made for every algorithm from every capture (H6), so a change of algorithm
  needs no new enrolment. Quality check (H15): the enrolment is kept only
  when every pair of its three captures matches with OpenCV SIFT at its
  threshold; otherwise one more placement is asked for. In H10, OpenCV SIFT
  matched 28 of 30 such pairs and none of 405 different-finger pairs.
- **Algorithms:** from the research, unchanged, through the pinned link
  (H10): OpenCV SIFT, Pore SIFT and the learned pore descriptor (its second
  training, H6); fusions with the research's weights or with user weights that
  sum to 100 (H6). Pore SIFT and the learned descriptor share one pore
  detection per capture, as in H10.
- **Verification (1:1, H15):** the user picks one of the enrolled fingers;
  the new capture is compared with its three templates, and the highest score
  decides.
- **Identification (1:N, H15):** the new capture is compared with every
  enrolled fingerprint template; candidates are ranked by their highest
  score, and the top one is reported only when it passes the threshold, else
  the result is "not found". The search time grows with the number of
  enrolled templates and is shown to the user.
- **Thresholds (H16):** settings per algorithm, kept in the biometric
  database; a comparison is accepted when its score is above its threshold.
  Administrators can change them in the client, each change enters the audit
  log, and every attempt records the threshold it used. At the SD302
  thresholds (RxJ), OpenCV SIFT accepted none of the researcher's 405
  different-finger pairs in H10, but Pore SIFT accepted 71 and the learned
  descriptor 28. The initial values:

  | Algorithm | Accept above | Origin | H10 same finger | H10 different fingers |
  | --- | --- | --- | --- | --- |
  | OpenCV SIFT | 57 | SD302 plain vs plain, FAR 0.1 % (RxJ) | 28 of 30 | 0 of 675 |
  | Pore SIFT | 37 | provisional: the highest H10 different-finger score | 13 of 30 | 0 of 675 |
  | Learned pore descriptor | 21 | provisional: the highest H10 different-finger score | 24 of 30 | 0 of 675 |

  "Same finger" counts the 30 placement pairs of the second set (H10, A);
  "different fingers" counts both comparisons of H10 (A and B). They are
  single comparisons of one person's fingers, the same-finger pairs from one
  session, so they claim no FAR, and the interface marks the pore thresholds
  as provisional. Against the first set, saved six weeks earlier through the
  vendor's window (H10, B), the same thresholds accepted 1, 1 and 11 of 30
  same-finger pairs. Taking the highest of three scores (1:1) accepts at
  least as often as one comparison, for the same finger and for different
  fingers alike.

  Fusion thresholds are set by the same rule from H10's saved scores when
  fusion is built (increment 6). Calibration with other people is not part of
  the build: if the supervisor asks for accuracy on the HiScan PRO, it is a
  separate step (about 10 people for a claim at FAR 1 % and about 20 at FAR
  0.1 %, as estimated on 2026-10-18), after which the thresholds change in
  the administration area with no change to the code.
- **Speed and size (H10, medians):** OpenCV SIFT 0.25 s per capture and
  0.15 s per comparison, with a 4.3 MB template; the pore methods 3.1 s per
  capture, almost all of it pore detection on one CPU thread (the system may
  use more threads), then 32 ms (Pore SIFT) or 0.5 ms (learned descriptor,
  GPU) per comparison, with templates of 0.83 MB and 0.41 MB.

### 5.2 Face

- **Capture:** the integrated camera, through the client.
- **Models:** YuNet for detection (MIT) and SFace for recognition (Apache
  2.0), from OpenCV Zoo, run with OpenCV in the system's face environment.
  SFace gives an embedding of fixed length (128 values according to secondary
  sources; read from the model file when the face engine is built); OpenCV's
  sample decides "same person" at cosine similarity 0.363 or more. OpenCV Zoo
  reports 99.4 % accuracy for SFace in its own evaluation.
- **Enrolment (H17):** three images, three embeddings.
- **1:1 and 1:N:** the highest cosine similarity over a user's embeddings;
  1:N searches the embeddings with pgvector.

### 5.3 Voice

- **Capture:** the microphone, through the client, as 16 kHz mono audio.
- **Model:** SpeechBrain's ECAPA-TDNN trained on VoxCeleb
  (`speechbrain/spkrec-ecapa-voxceleb`, Apache 2.0): a 192-value embedding
  compared by cosine similarity; SpeechBrain's verification threshold is 0.25,
  and the model card reports an EER of 0.80 % on VoxCeleb1.
- **Enrolment (H17):** three recordings of about four seconds, the user
  reading a sentence shown in Hebrew; the model does not depend on the text.
- **1:1 and 1:N:** as for the face.

Model files are downloaded only with the researcher's approval and pinned by
SHA-256.

## 6. User experience (H6)

| Screen | Content |
| --- | --- |
| Registration | username, email, password, national ID, with the promise that the ID is never stored; an ID already registered is refused |
| Login | email or username, password; a user account opens the home screen, an administrator account the administration area |
| Home | three modality cards, fingerprint first, with each one's enrolment status |
| Settings (H24) | the theme: light, dark, or Windows' setting (the default), saved per account and applied at once; sign-in and registration follow Windows' setting |
| Modality | enrol, verify (1:1), identify (1:N); before enrolment, verify and identify lead to the message of section 5 |
| Algorithm choice | one card per algorithm: accuracy, speed, what its template holds and how two templates are compared (H2), in two or three sentences with a small drawing, and whether its threshold is provisional; OpenCV SIFT first, then the learned pore descriptor, Pore SIFT and the fusions (H18); face and voice have one model each, shown on its card without a choice |
| Fingerprint capture | scanner status, finger and placement guide, "lift the finger" between placements, the captured print and its checks |
| Face capture | live camera view with the detected face box |
| Voice capture | the sentence to read, a level meter and a timer |
| 1:1 result | the new print beside the enrolled one with lines between matched points or pores, a score gauge marked with the threshold, the decision and the time it took |
| 1:N result | an animated pass over the enrolled gallery, the ranked candidates with their scores, the top one marked when it passes the threshold |
| Administration area (H12) | accounts with role and status, new administrators, disabling and enabling; the attempt history with filters; thresholds; the audit log; never national IDs or samples |

OpenCV SIFT comes first because its threshold is the only one that is not
provisional on the HiScan PRO, it did best there (28 of 30 same-finger pairs,
none of 675 different-finger pairs) and its 1:1 is the fastest (0.4 s); the
learned pore descriptor, the research's own method, comes next.

Accuracy shown for fingerprint algorithms (H18): the SD302 plain vs plain
test result, measured on other scanners at the SD302 thresholds (TAR at FAR
0.1 %: learned descriptor 95.1 % and 93.4 %, Pore SIFT 77.9 % and 78.5 %,
OpenCV SIFT 70.8 % and 68.1 %, RxJ and QxJ), in plain words, because its
sample is far larger than the HiScan check of H10. It stays so until the
thresholds are calibrated with other people (H16); the cards still mark the
provisional thresholds. For the drawings, the engines also
return the matched coordinates; only the research score decides (H18). In 1:N
results, other users appear as "another registered user", without their
names, and drawings use only the user's own prints (H18).

## 7. Attempts and audit (H6, H12)

Every attempt is stored in the biometric database: time, modality, algorithm,
mode (1:1 or 1:N), score, threshold, decision, duration, the encrypted sample,
the subject of the logged-in user and, in 1:N, the top candidate's enrolment,
and so its subject (H25). Only subject identifiers are stored; the
administration area turns them into usernames through the identity link.

Administrative changes are stored in the audit log of the accounts database:
time, administrator, action and target (an account, or the algorithm whose
threshold changed).

## 8. Repository and environments

```
client/    Electron + React + TypeScript (npm, lock file)
server/    FastAPI application
engines/   engine processes: fingerprint (through methods/), face, voice
methods/   pinned research link (H10)
scanner/   ScannerCapture (H7–H9) and its acquisition mode for the server
docs/      this specification, decisions, validations
```

New environments, each with exact versions: the server (Python 3.12,
FastAPI, a PostgreSQL driver, `cryptography`), face (OpenCV), voice
(SpeechBrain with PyTorch), PostgreSQL with pgvector, and the client's npm
packages. Node.js 24 is installed (24.18.0); PostgreSQL is not. PostgreSQL
and pgvector come from conda-forge, like the research environments (H19). The
only Windows build of pgvector 0.8.6, its newest version, is built for
PostgreSQL 16.15 (it requires libpq 16.15), which conda-forge also builds for
Windows, so the pair is PostgreSQL 16.15 with pgvector 0.8.6 (checked on
2026-10-20). Docker's `pgvector/pgvector` image is the fallback (Docker
Desktop is installed). Every download needs the researcher's approval. The
research environments stay unchanged.

## 9. Build increments (H20)

Each increment works end to end, comes with automated tests, and is approved
and reported on its own.

1. Foundation: environments, PostgreSQL with pgvector, the server, the
   accounts database, registration with the national ID, login, the roles
   with the first administrator's command and the accounts part of the
   administration area, keys, and the Hebrew client shell with its home
   screen and its settings in both themes (H24).
2. Fingerprint enrolment and 1:1 with OpenCV SIFT: the scanner's acquisition
   mode, the engine, encrypted storage and the attempt history.
3. All fingerprint algorithms, the algorithm choice, 1:N and the match
   drawings.
4. Face: enrolment, 1:1 and 1:N.
5. Voice: enrolment, 1:1 and 1:N.
6. The rest of the administration area (attempt history, thresholds),
   fusion and the finished experience.

## 10. Decisions

- **H11** One PC, localhost only (section 1).
- **H12** Separate administrator accounts, the first by a server command and
  the administration in the client, with role checks on the server,
  re-authentication and an audit log (2).
- **H13** Engines as child processes that keep no data between requests,
  exchanging JSON headers with binary data and comparing 1:N in parallel; the
  scanner's file-less acquisition mode (3).
- **H14** The cryptography: HMAC for the national ID, HKDF keys per record,
  AES-256-GCM with key versions and associated data, Argon2id, hashed session
  tokens, face and voice embeddings in pgvector, a user-only key file with a
  backup (4).
- **H15** The flow without enrolment, the enrolment check, the 1:1 and 1:N
  rules (5, 5.1).
- **H16** Thresholds as audit-logged settings with their initial values, the
  rule for fusion thresholds, and calibration as a separate later step (5.1).
- **H17** Three images or recordings for face and voice enrolment (5.2, 5.3).
- **H18** Matched coordinates for the drawings, other users unnamed in 1:N
  results, the order of the algorithm cards and the SD302 accuracy on them
  (6).
- **H19** PostgreSQL 16.15 with pgvector 0.8.6 from conda-forge, started by
  the server under the user's account; Docker as the fallback (3, 8).
- **H20** The six build increments (9).
- **H24** Light, dark or Windows' theme, chosen in the settings and saved per
  account (4, 6, 9).
- **H25** The exact data model of `docs/data-model.md`: several findings per
  person, one template per finding and method, sealed values bound to their
  subject (4, 7).
- **H26** The client's main process as its only network client, keeping the
  session token, behind a preload bridge with a fixed list of routes (3).
