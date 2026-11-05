# Engines

Long-running child processes of the server (H13): each loads its method once,
answers one request at a time on standard input and output, and keeps nothing
between requests. A message is one line of JSON with `length` (and `parts`
when the data has several), followed by its bytes (`protocol.py`, standard
library only). The server starts the engines when it starts and runs them in
the research project environment, which has numpy; they add no package to it.

| Engine | Operations | Decision |
| --- | --- | --- |
| `opencv_sift.py` | `extract` a PNG: keypoints, the template (the research's `.npz` layout), and the points and descriptors for the template screen; `compare` two templates: the research's score (RANSAC inliers) | H10, H33 |
| `nfiq2_quality.py` | `quality` of a PNG: NIST's NFIQ 2.3 score, 0 to 100, of a 500 ppi copy made in memory | H33 |

The OpenCV SIFT engine checks the pinned research link before it answers
(`methods/research_link.py`). The research's extraction reads an image file,
and a capture never reaches the disk unsealed (H13), so the engine decodes the
PNG in memory and makes the same OpenCV call; `test_engines.py` shows the
result equals the research function's.

## NFIQ 2

The released NFIQ 2.3.0 C interface cannot load its own 2.3 model (a stale
checksum, NIST's [issue 409](https://github.com/usnistgov/NFIQ2/issues/409),
fixed in the source on 2026-09-30, not yet released), and the released tool
reads only files. The system therefore builds NIST's v2.3.0 with only that fix,
as a library without the command-line tool, which needs three of the tag's
components: OpenCV 4.10.0, FingerJet FX OSE and digestpp. With Visual Studio
2026 (C++ and its CMake), from a Developer Command Prompt for x64:

```bat
git clone --depth 1 --branch v2.3.0 https://github.com/usnistgov/NFIQ2.git
cd NFIQ2
git submodule update --init --depth 1 opencv fingerjetfxose digestpp
curl -L -o fix.patch https://github.com/usnistgov/NFIQ2/commit/6ebcd52a6686f2b43ef3bba48a0b033655ef7d20.patch
git apply fix.patch
rem NFIQ 2.3.0 declares CMake 3.3; CMake 4 needs a policy minimum to configure it.
set CMAKE_POLICY_VERSION_MINIMUM=3.5
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_NFIQ2_CLI=OFF
cmake --build build --parallel
```

Copy `build\install_staging\nfiq2\bin\Nfiq2Api.dll` and the model files
`NFIQ2\nist_plain_tir-ink.yaml` and `.txt` into one folder outside the
repository (the system uses the git-ignored `local/`), and name that folder as
`nfiq2_bin` in `local/server.toml`. The engine refuses a library that is not
2.3.0 or that does not load the 2.3 model (hash
`b4a1e7586b3be906f9770e4b77768038`). Nothing is installed into Windows; the
library depends only on `KERNEL32.dll`, like the released one. On 2026-11-05
this build gave, from memory, exactly the released tool's scores on the
researcher's 40 captures and on damaged copies of them.

## Tests

```bash
# PY: the research project environment's python.exe, with its folders on PATH
PY -m pytest engines -p no:cacheprovider
```

Synthetic ridge images only. The OpenCV SIFT tests need the research checkout
of `local/research.toml`; the NFIQ 2 test needs the library, named by
`MBS_NFIQ2_BIN` or `nfiq2_bin` in `local/server.toml`. Tests whose
requirements are missing are skipped.
