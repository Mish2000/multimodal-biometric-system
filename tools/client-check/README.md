# Offscreen check of the client

An end-to-end check of the built client (H26) against a throwaway server: the real page, preload, bridge and window
security in Electron, offscreen, and the real API with its own PostgreSQL cluster, keys held only in memory and free
ports. It never touches the real cluster or key file, and it opens nothing on the desktop.

It uses synthetic data only: the accounts are made up, the camera is Chromium's own synthetic one (H48), and the
microphone plays a recording that `voice_files.py` computes (H54). Fingerprint captures are a person's, so none is in
the repository: `--captures` names a git-ignored folder of ScannerCapture's captures (H9), whose files the check picks
by finger position and placement.

```bash
# from the repository root, with the multimodal-server environment, after `npm run build` in client/
python tools/client-check/run.py NAME                                  # what needs no engine
python tools/client-check/run.py NAME --captures DIR --identify       # the fingerprint engines, 1:1 and 1:N
python tools/client-check/run.py NAME --face --voice                   # the face and voice engines
```

Without options it checks registration with the mobile phone and the password meter, sign-in, sign-out, password
recovery through the outbox, the theme and the language in both directions, the administrator's one-time password,
disabling an account and a new administrator. The options add the engines, each found as the server finds it
(`local/server.toml`): `--captures DIR` with `--identify`, `--pore`, `--learned`, `--match-view` and
`--identify-methods` for the fingerprint methods, and `--face` and `--voice` for the other modalities; `--page URL`
checks the development server's page (`dev_server.mts`) instead of the built one.

Everything the check writes goes to the git-ignored `local/client-check/`: `NAME-server.log`, `NAME-check.log`,
`shots-NAME/` and `run-NAME/`, whose throwaway cluster is removed at the end. The check without options also runs on
GitHub's runners with every push (`.github/workflows/checks.yml`).

| File | What it does |
| --- | --- |
| `run.py` | starts the throwaway server, runs the check in Electron, then stops the server |
| `throwaway_server.py` | the server with its own cluster, as the server's tests make theirs |
| `check.mts` | the check itself, in Electron's main process |
| `voice_files.py` | the synthetic recordings: the microphone's WAV, the same as an MP3 file and at 8 kHz |
| `dev_server.mts` | the renderer's development server without Electron |
| `tsconfig.json` | the type check of the two TypeScript files, run by the client's `npm run typecheck` |

`check.mts` and `dev_server.mts` are TypeScript that Electron and Node.js run as it is, removing the types when they
load a file. The client's `npm run typecheck` checks those types, against the types of the client's own bridge and
window, and its `npm run lint` lints both files.
