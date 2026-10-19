# Research methods (H10)

The system uses the fingerprint methods of
[fingerprint-level3-recognition-research](https://github.com/Mish2000/fingerprint-level3-recognition-research)
without copying them: a local checkout is imported in its own Python
environments, pinned and checked by `research_link.py` against
`research-pin.toml` (commit, SHA-256 of the research artefacts outside git,
and the plain vs plain thresholds). The link only reads the research
checkout; outputs stay in this repository's ignored `captures/`.

Machine paths go in the ignored `local/research.toml`:

```toml
repository = "<research checkout>"
project_python = "<conda envs>/fingerprint-level3-recognition-research/python.exe"
gpu_python = "<conda envs>/fingerprint-level3-gpu/python.exe"
```

The Pore SIFT environment comes from the research's `configs/algorithms.toml`.
The research environments must load their compiled libraries from their own
folders, so the scripts put them on `PATH` for every stage, as `conda
activate` would.

```powershell
# Tests of this folder's own logic (project environment, which has pytest)
& $projectPython -m pytest methods -p no:cacheprovider
# The three methods on the second and first capture sets (H10); about 5 minutes
& $projectPython methods/hiscan_eval.py --first '<first-set folder>'
```

`hiscan_eval.py` refuses to run unless the research checkout and its pinned
files are exactly the pinned ones, and refuses to write over an earlier
evaluation folder. `--fingers 1-2 --out captures/live002/evaluation-pilot`
runs a small pilot first. Results: `docs/hiscan-methods.md`.
