# Server (increments 1 to 4 of H20)

The FastAPI server of the system: the local PostgreSQL cluster, the key file, registration with the
national ID and the mobile phone, sign-in, password recovery, roles and the accounts part of the
administration (H3, H11, H12, H14, H19, H29 to H32), fingerprint enrolment (H33)
and 1:1 verification with OpenCV SIFT, Pore SIFT and Pore CNN
(H35, H38, H39) and 1:N identification (H41, H42) with all three methods, and face enrolment (H48),
1:1 verification (H49) and 1:N identification (H50).
It runs with the `multimodal-server` environment and starts PostgreSQL from the
`multimodal-postgres` environment (`environments/`); the face engine runs in `multimodal-face`.

```powershell
conda create -n multimodal-server --file environments/server-win-64.lock
conda create -n multimodal-postgres --file environments/postgres-win-64.lock
conda create -n multimodal-face --file environments/face-win-64.lock   # and the two models: engines/README.md
cd server
$python = '<conda envs>\multimodal-server\python.exe'
& $python -m mbs setup        # key file, local/server.toml, cluster, both databases (safe to rerun)
& $python -m mbs create-admin --username <name> --email <address>   # prints a one-time password
& $python -m mbs serve        # the API on 127.0.0.1; starts and stops PostgreSQL with it
& $python -m mbs db status    # or start / stop
& $python -m pytest           # 247 tests against a throwaway cluster (four need MBS_LIVE_CAPTURES)
```

## Machine settings

`setup` writes the git-ignored `local/server.toml` with this machine's defaults:

| Setting | Default |
| --- | --- |
| `postgres_bin` | `Library/bin` of the `multimodal-postgres` environment |
| `data_dir` | `local/postgres/data` |
| `database_port` | 55432, on localhost only |
| `key_file` | `%LOCALAPPDATA%\multimodal-biometric-system\keys.json` |
| `server_port` | 55433, on 127.0.0.1 only |
| `scanner_driver_dir` | none: the supplied `fx_hs_windows_10_driver_v3.3` folder (H8), for fingerprint enrolment |
| `scanner_exe` | `scanner/ScannerCapture/bin/Release/net48/ScannerCapture.exe`, built from `scanner/` |
| `nfiq2_bin` | `local/nfiq2/2.3.0-fix/bin` when it holds `Nfiq2Api.dll`: the NFIQ 2 build of `engines/README.md` |
| `face_python` | `python.exe` of the `multimodal-face` environment beside the server's, when it exists (H48) |
| `face_models` | `local/models/face` when it exists: YuNet and SFace, pinned by SHA-256 (`engines/README.md`) |

Fingerprint enrolment also needs the research project environment of `local/research.toml` (H10),
which runs the engines (`engines/`). Without any of these the server runs as before, says at its start
what is missing, and answers enrolment requests with `fingerprint_unavailable`. The face settings fall back
to their defaults when `local/server.toml` does not name them; without them the face routes answer
`face_unavailable`.

## Keys and data

- **Key file** (H14): created once by `setup` and never replaced. Inherited permissions are removed and
  only the current Windows user has access, to the file and to its folder. It holds a master secret
  per key version, the HMAC key of national IDs and the database passwords. Keep a backup copy: without
  it nothing stored can be read or linked to its accounts.
- **Databases** (H4, H19): `mbs_accounts` and `mbs_biometric`, each owned by its own login role and
  closed to every other role; pgvector is installed in the biometric one. PostgreSQL listens on
  localhost, takes SCRAM passwords and runs under the user's account through `pg_ctl`.
- **National ID** (H3): checked by its check digit, kept only as HMAC-SHA256, never logged. A second
  account with the same ID is refused.
- **Identity link** (H3, H14): each user account has a random subject in the biometric database; the
  link is the subject identifier sealed with AES-256-GCM under a key derived by HKDF-SHA256 from the
  current master secret, a random salt per record and the label `mbs/identity-link/v1`. Each sealed
  value records its key version and is bound to its account as associated data.
- **Passwords** (H14, H30): Argon2id (3 passes, 4 lanes, 64 MiB, 128-bit salt, 256-bit tag) as PHC
  strings, after NFKC normalisation; 8 to 32 characters with at least one uppercase letter and one
  digit. Passwords set before H30 keep working until they are changed.
- **Mobile phone** (H29): kept in E.164 form and unique; 05X-XXXXXXX is read as an Israeli mobile.
- **Language** (H31): `en` (the default) or `he` per account, from registration, a sign-in that names
  one, or the settings.
- **Password recovery** (H32): a link by SMS or email, with a random token stored only as SHA-256,
  working once and for 30 minutes; the same answer whether the details belong to an account or not,
  at most one message per account a minute, and every session signed out after the change. Until a
  provider is chosen, each message is an HTML page in the git-ignored `local/outbox/`; the server's
  window names the new file, whose `mbs://` link opens the client.
- **Sessions** (H14): random tokens, stored only as SHA-256; they end after 30 minutes without use
  and 12 hours at most. Changing a password signs the account's other sessions out.
- **Fingerprint enrolment** (H15, H25, H33): the three kept captures of a finger are sealed in
  `sample` under the label `mbs/sample/v1`, bound to the sample and its subject, and their OpenCV SIFT
  templates in `template` under `mbs/template/v1`, bound to the template, its subject and its
  algorithm. Only the engines read templates; the template screen gets its data once, from memory,
  before sealing. A new enrolment of the same finger replaces the old one, which stays.
- **Sign-in** (H14): email or username, the same answer for an unknown name and a wrong password.
  After five failures for one name, each further try waits 2, 4, 8 ... seconds, at most five
  minutes (in memory: one server process on one PC, H11).

## Roles (H12)

- Every route declares who may call it; a route without a declaration is refused, and the check runs
  on the server for every request. A test fails if a route has no declaration.
- User accounts register in the client. Administrator accounts are separate: no national ID, no
  subject. The first comes from `create-admin`, further ones from an administrator in the client; each
  starts with a one-time password and can do nothing else until it is replaced.
- Creating an administrator and disabling or enabling an account ask for the administrator's password
  again and enter the audit log, which a database trigger keeps insert-only. A disabled account
  loses its sessions and cannot sign in; the last active administrator cannot be disabled.

## API

| Route | Who | Purpose |
| --- | --- | --- |
| `GET /api/health` | anyone | the server answers |
| `POST /api/register` | anyone | a user account |
| `POST /api/login`, `POST /api/logout` | anyone, signed in | a session (`Authorization: Bearer <token>`) |
| `GET /api/me`, `POST /api/me/password` | signed in | the account and its enrolments; a new password |
| `POST /api/me/theme`, `POST /api/me/language` | signed in | the account's theme (H24) and language (H31) |
| `POST /api/password-reset` | anyone | a recovery link by SMS or email (H32), answered 202 either way |
| `POST /api/password-reset/check`, `POST /api/password-reset/complete` | anyone with a link | whether the link works; the new password |
| `POST /api/fingerprint/enrolments` | user | enrol a finger (`{"finger": 1-10}`); the answer is a stream of JSON lines, one event each (`started`, `place`, `kept`, `rejected`, `lift`, `another_placement`, then `saved` or `failed`); closing it cancels the enrolment (H33) |
| `DELETE /api/fingerprint/fingers/{finger}` | user | delete a finger's current and replaced enrolments, their captures, templates and verification attempts with their probes (H34, H35); 404 when it is not enrolled |
| `POST /api/fingerprint/verifications` | user | verify the chosen finger (`{"finger": 1-10, "algorithm": "opencv-sift"}`) against the selected method's three current templates, with H33 quality checks. Streamed events end in `verified` or `failed` (H35, H38) |
| `GET /api/fingerprint/methods` | user | implemented methods with their threshold, origin, provisional flag and local availability (H38) |
| `POST /api/fingerprint/identifications` | user | identify a new fingerprint against current active enrolments using `opencv-sift` (default), `pore-sift` or `learned-pore`, with streamed progress ending in `identified` or `failed` (H41, H42) |
| `GET /api/face/method` | user | SFace's threshold, its origin, whether the face engine is set up, and the enrolment's rules (H48) |
| `POST /api/face/detect` | user | the faces of one small frame of the live view (`{"image": base64}`, at most 1 MB): boxes, landmarks and scores; nothing is kept |
| `POST /api/face/checks` | user | one taken image (a PNG of the camera's frame, at most 8 MB): its checks and, when it passes, its aligned face; nothing is kept |
| `POST /api/face/enrolments` | user | three to six taken images with their times, in order: 201 `saved` when three match each other, otherwise 200 `another`, or `failed` after six |
| `POST /api/face/verifications` | user | verify the face with one taken image (H49): `rejected` with its checks and no attempt, or `verified` with the three scores, the decision and the two aligned faces, sent after the attempt is saved; 409 `not_enrolled` before an enrolment |
| `POST /api/face/identifications` | user | identify the face with one taken image (H50): `rejected` with its checks and no attempt, or `identified` with the five leading enrolments (the caller's own marked, others anonymous), the tie count, the gallery's size and, when the caller's enrolment is among the five, the two aligned faces, sent after the attempt is saved; 409 `not_enrolled` before an enrolment, 409 `gallery_changed` when the gallery changed during the search |
| `DELETE /api/face/enrolment` | user | delete the face's current and replaced enrolments with their images, embeddings and verification attempts; identification attempts stay, without the link; 404 when it is not enrolled |
| `GET /api/admin/accounts`, `POST /api/admin/accounts/{id}/status` | administrator | accounts; disable or enable |
| `POST /api/admin/administrators`, `GET /api/admin/audit` | administrator | a new administrator; the audit log |

Errors answer `{"error": "<code>"}`; the client turns codes into English or Hebrew text.

Verification uses the existing capture and engine settings. On startup, `serve`
applies the biometric migrations through `biometric_0005` (H48), preserving enrolled
fingers and attempts while updating identification retention (H41).
The highest of the three scores decides, strictly above the threshold; a result
is sent only after storage. Its probe is sealed under `mbs/probe/v1`, bound to
the attempt and its subject. Deleting a finger cascades to the verification
attempts of all its enrolments, including their probes (H35).

Verification accepts `algorithm`: `opencv-sift` (the default), `pore-sift`
(H38), or `learned-pore` (H39). Pore SIFT uses the environment named in the
checked research configuration; Pore CNN uses `gpu_python` in
`local/research.toml` and the pinned second model. New enrolments produce all
available templates together; existing ones receive missing templates from
their sealed samples before a new capture. Preparation emits
`preparing_templates` during verification and `templates` during enrolment.
Pore SIFT and learned scores must be strictly above their provisional
thresholds of 37 and 21 respectively. Every method uses the same encrypted
tables and quality gate; enrolment's fixed pairwise referee is OpenCV SIFT.
The saved enrolment event also carries `method_comparisons`, each method's
three placement-pair scores and threshold for the completion screen, without
changing the referee. Shared pore coordinates stay in memory.

OpenCV SIFT verification also returns `match_view` (H43), containing the
highest-scoring placement's sealed capture opened for the caller, the count
of inliers, and their native coordinate pairs. The pair count must equal
the deciding score. The image is restricted to the caller's current
enrolment and sent with the committed result. Its presentation data stays
in the page for that result. The processing timer ends after the comparisons,
before opening the stored image for presentation.

H44 returns `match_view` for Pore SIFT and Pore CNN too. Pore
SIFT pairs come from each scoring comparison, as in H43.
For Pore CNN, the server repeats the winning comparison once with the pores
both templates were described from: the probe's detection in this run, and
for the stored capture this run's preparation, its Pore SIFT template, or
the pinned detector. The repeated score must equal the deciding score.

Identification requires the caller to have an enrolled finger (H15). It fixes
the gallery of current enrolments belonging to active user accounts and the
threshold at the start. H42 prepares any missing templates of the selected
pore method from sealed captures before requesting a new scan. Each enrolled
finger's missing templates commit together, and retry reuses completed work.
Identification extracts the new capture once and compares its template to the
selected method's stored templates. CPU engines use groups of up to four
independent processes, and Pore CNN uses one runtime. Gallery
metadata spans the search, while the reference data is loaded for each group.
The server rechecks participating accounts, enrolments and template membership
before committing. Cancellation interrupts computation and waits for cleanup.
Events include `started`, `preparing_templates`, `place`, `checking`,
`rejected`, `lift`, `captured`, `extracting`, `searching` and `saving`.
The terminal `identified` event carries
the five leading enrolments and their scores, the total number of enrolments
and templates, and the number of equal leaders. Other candidates have only
per-attempt ranks and anonymous labels. The caller's own finger positions
are included. H45 adds `match_view` for the caller's highest-ranked own
enrolment among those five, with its rank, finger and placement: the server
repeats that enrolment's winning comparison once with `view` (Pore CNN with its pores, as in H44)
and requires the same score. No other
user's capture is opened for it. The attempt stores its leading enrolment even for a non-match.
Deleting that enrolment sets the link to null and retains the attempt and
its sealed probe, as stated in the client confirmation (H41).

To check the real engines against the existing second capture set, set
`MBS_LIVE_CAPTURES` to `../captures/live002` before running pytest. The local
checks cover enrolment, verification and identification with all three methods.
Search results must equal serial comparison of the same native templates.
Prepared pore templates are compared with the H10 reference templates.
Manual validation uses the real scanner in the client.

Face enrolment (H48) keeps nothing between requests: the page sends the images that passed their checks,
in the order they were taken, and the server checks each again (exactly one face, YuNet's score of at
least 0.9, the whole face inside the image, at least 112 pixels wide). It compares every pair by
pgvector's cosine similarity and keeps the three whose lowest pair is highest, when all three pairs are
above SFace's threshold of 0.363, as H15 does for fingerprints. The kept images are sealed under
`mbs/sample/v1` with their checks; their embeddings are `vector` values of 128 numbers, unsealed (H14),
under the SFace model's SHA-256 as their version. A face engine that reports another SFace file is refused
(`method_version_differs`). Migration `biometric_0005` adds SFace's row to the algorithm table.

Face verification (H49) compares one taken image that passes H48's checks with the caller's three
current SFace embeddings in one SQL statement (pgvector's cosine similarity). The highest score decides,
strictly above 0.363; equal scores go to the earliest image. The time runs from the image's receipt to the
end of the comparisons. The winning stored image is then opened for its owner only and extracted again:
its embedding must equal the stored one, or the run ends unsaved. The attempt is saved with its image
sealed under `mbs/probe/v1`, while the enrolment is locked and still current (otherwise
`enrolment_changed`), and only then is the answer sent.

Face identification (H50) fixes its gallery when the image arrives, as H41 does for fingerprints: the
current face enrolments of the active user accounts, through their sealed identity links, each with three
SFace embeddings of the pinned version. One SQL statement ranks the enrolments by their highest cosine
similarity, an exact search without an index; the leader is found only strictly above 0.363, and equal
leaders are ordered by enrolment and reported as a tie. When the caller's own enrolment is among the five
shown, its winning image is extracted again as in H49. The accounts, then the enrolments and their
templates are locked and checked again before the attempt is saved (otherwise `gallery_changed`); the
leading enrolment is stored even below the threshold, and its later deletion keeps the attempt (H41).

Cancellation closes the acquisition worker's standard input (H36). The worker
finishes its current native call, switches off the illumination (H37),
restores the previous DPI and closes the channel. A 10-second watchdog bounds
cleanup. Persistent
`FXOEM_OpenChannel` status 110 is logged and reported as
`scanner_connection_failed`, distinct from a generic capture failure.

## Known limits

- libpq's GSSAPI encryption is switched off for every connection: with libpq 18.6 from conda-forge it
  crashes the process on this PC, and the cluster only takes SCRAM passwords on localhost.
- Activity times in the two databases (sessions here, attempts from increment 2 on) could let someone
  who has both databases, but no key, guess which subject belongs to which account. Subjects carry no
  creation time for that reason.
- Starlette 1.9 warns that its test client prefers `httpx2` over `httpx`; the tests pass with `httpx`.
