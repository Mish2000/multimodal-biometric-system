# Server (increments 1 and 2 of H20)

The FastAPI server of the system: the local PostgreSQL cluster, the key file, registration with the
national ID and the mobile phone, sign-in, password recovery, roles and the accounts part of the
administration (H3, H11, H12, H14, H19, H29 to H32), fingerprint enrolment (H33)
and 1:1 verification (H35).
It runs with the `multimodal-server` environment and starts PostgreSQL from the
`multimodal-postgres` environment (`environments/`).

```powershell
conda create -n multimodal-server --file environments/server-win-64.lock
conda create -n multimodal-postgres --file environments/postgres-win-64.lock
cd server
$python = '<conda envs>\multimodal-server\python.exe'
& $python -m mbs setup        # key file, local/server.toml, cluster, both databases (safe to rerun)
& $python -m mbs create-admin --username <name> --email <address>   # prints a one-time password
& $python -m mbs serve        # the API on 127.0.0.1; starts and stops PostgreSQL with it
& $python -m mbs db status    # or start / stop
& $python -m pytest           # 121 tests against a throwaway cluster (one needs MBS_LIVE_CAPTURES)
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

Fingerprint enrolment also needs the research project environment of `local/research.toml` (H10),
which runs the engines (`engines/`). Without any of these the server runs as before, says at its start
what is missing, and answers enrolment requests with `fingerprint_unavailable`.

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
| `POST /api/fingerprint/verifications` | user | verify the chosen finger (`{"finger": 1-10}`) against its three current OpenCV SIFT templates, with H33 quality checks; streamed events `started`, `place`, `checking`, `rejected`, `lift`, `captured`, `comparing`, `saving`, then `verified` or `failed` (H35) |
| `GET /api/admin/accounts`, `POST /api/admin/accounts/{id}/status` | administrator | accounts; disable or enable |
| `POST /api/admin/administrators`, `GET /api/admin/audit` | administrator | a new administrator; the audit log |

Errors answer `{"error": "<code>"}`; the client turns codes into English or Hebrew text.

Verification uses the existing capture and engine settings. On startup, `serve`
applies `biometric_0003`, preserving enrolled fingers and adding `attempt`.
The highest of the three scores decides, strictly above the threshold; a result
is sent only after storage. Its probe is sealed under `mbs/probe/v1`, bound to
the attempt and its subject. Deleting a finger cascades to the verification
attempts of all its enrolments, including their probes (H35).

To check the real engines against the existing second capture set, set
`MBS_LIVE_CAPTURES` to `../captures/live002` before running pytest. The local
check enrols a finger, verifies it and rejects another finger using those
stored captures. Manual validation uses the real scanner in the client.

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
