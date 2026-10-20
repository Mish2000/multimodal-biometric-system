# Server (increment 1 of H20)

The FastAPI server of the system: the local PostgreSQL cluster, the key file, registration with the
national ID, sign-in, roles and the accounts part of the administration (H3, H11, H12, H14, H19).
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
& $python -m pytest           # 42 tests against a throwaway cluster, about a minute
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
- **Passwords** (H14): Argon2id (3 passes, 4 lanes, 64 MiB, 128-bit salt, 256-bit tag) as PHC
  strings, after NFKC normalisation; 12 to 256 characters, no composition rules.
- **Sessions** (H14): random tokens, stored only as SHA-256; they end after 30 minutes without use
  and 12 hours at most. Changing a password signs the account's other sessions out.
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
| `GET /api/admin/accounts`, `POST /api/admin/accounts/{id}/status` | administrator | accounts; disable or enable |
| `POST /api/admin/administrators`, `GET /api/admin/audit` | administrator | a new administrator; the audit log |

Errors answer `{"error": "<code>"}`; the client turns codes into Hebrew text.

## Known limits

- libpq's GSSAPI encryption is switched off for every connection: with libpq 18.6 from conda-forge it
  crashes the process on this PC, and the cluster only takes SCRAM passwords on localhost.
- Activity times in the two databases (sessions here, attempts from increment 2 on) could let someone
  who has both databases, but no key, guess which subject belongs to which account. Subjects carry no
  creation time for that reason.
- Starlette 1.9 warns that its test client prefers `httpx2` over `httpx`; the tests pass with `httpx`.
