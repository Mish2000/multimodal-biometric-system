# Engines

Long-running child processes of the server (H13): each loads its method once,
answers one request at a time on standard input and output, and keeps nothing
between requests. A message is one line of JSON with `length` (and `parts`
when the data has several), followed by its bytes (`protocol.py`, standard
library only). The server runs OpenCV SIFT and NFIQ 2 in the research project
environment, Pore SIFT in its existing research environment, and Pore CNN in the research GPU environment.
They add no package. The face engine runs in its own environment,
`multimodal-face` (`environments/face.yml`, H48), and the voice engine in `multimodal-voice`
(`environments/voice.yml`, H54).

| Engine | Operations | Decision |
| --- | --- | --- |
| `opencv_sift.py` | `extract` a PNG: keypoints, the template (the research's `.npz` layout), and the points and descriptors for the template screen; `compare` two templates: the research's score (RANSAC inliers) | H10, H33 |
| `nfiq2_quality.py` | `quality` of a PNG: NIST's NFIQ 2.3 score, 0 to 100, of a 500 ppi copy made in memory | H33 |
| `pore_sift.py` | `extract` a native PNG to the research's NPZ template; `compare` two templates by its basic matcher, with the research's detector, NMS and descriptor functions | H10, H38 |
| `learned_pore.py` | `extract` a native PNG and shared pore coordinates to the second model's native float16 NPY template; `compare` by the research's batched matcher | H6, H10, H39 |
| `face.py` | `detect` the faces of an image: boxes, five landmarks and YuNet's scores; `extract` for exactly one face: the image again as a PNG of its pixels, the aligned 112 x 112 face and SFace's 128 float32 values; images above 1920 pixels are scaled down first | H48, H51 |
| `voice.py` | `extract` a WAV of 16 kHz, one channel and 16-bit PCM: its length, seconds of speech, levels and clipped share; for a second or more, the recording again as a WAV of its samples and ECAPA-TDNN's 192 float32 values | H54 |

Pore SIFT starts on demand. Its short configuration check runs in the research
project Python, which can read the research TOML files and verify the pin.
The persistent engine runs in the Python 3.10 environment named by the
research's `configs/algorithms.toml`. The upstream NMS functions keep their
parameters and coordinate writer; their image output is discarded and the
coordinate text goes to a memory buffer. No sample or derived file is written.
The engine keeps integer row/column points and float32 descriptors in the
research's native NPZ layout. The synthetic test compares it with the unchanged
file-based research worker; local validation also reproduced all 30 second-set
templates and 435 H10 scores exactly.

H39 also exposes `detect`, returning the same integer coordinates in memory
without computing SIFT descriptors. New enrolments pass the existing Pore
SIFT template's coordinates to Pore CNN, detecting once per
capture. The Pore CNN engine verifies the research pin and model hash, calls
the unchanged 32 x 32 window selector and description function, then stores
and scores half-precision descriptors exactly as H10 does. Templates and
all 435 second-set scores were reproduced exactly. No coordinate or capture
file is created, and neither engine retains a finding between requests.

The OpenCV SIFT engine checks the pinned research link before it answers
(`methods/research_link.py`). The research's extraction reads an image file,
and a capture never reaches the disk unsealed (H13), so the engine decodes the
PNG in memory and makes the same OpenCV call; `test_engines.py` shows the
result equals the research function's.

For H43, `compare` accepts `view = true` and returns the counted matches
as binary float32 rows `(probe_x, probe_y, reference_x, reference_y)`, with
their count in `matches`. A scoped OpenCV binding observes the arguments and
returned mask of the research's own `findHomography` call. The observed
inliers must equal the score, and the binding is restored when the call
ends. The engine serves one request at a time. Local checks reproduced all
435 H10 scores and verified that each coordinate belongs to its template.

For H44, both pore engines accept `view = true` and return the same rows for
the pore pairs that their score counts: mutual nearest descriptors that pass
the 0.7 ratio check, with no geometric check. Pore SIFT observes the list
returned by the pinned matcher's `find_correspondences` through a scoped
binding and maps its probe and reference indices to the template's (row,
column) pores as (x, y). A Pore CNN template holds descriptors only, so its
viewed comparison also takes the pores that each template was described
from. The engine scores with the unchanged `batched_scores`, recomputes the
counted rows with the same operations for that one reference, and finds each
row's pore by running the research's `image_patches` on an image of pixel
positions. The pair count must equal the score, and the described pores must
match the template's rows. For both methods, local checks reproduced all 435
H10 scores and placed every pair on a native pore of its template.

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

## Face

The face engine uses two models from [OpenCV Zoo](https://github.com/opencv/opencv_zoo), each pinned by
SHA-256; the engine refuses any other file. They are kept in the git-ignored `local/models/face`, or in
the folder named by `face_models` in `local/server.toml`:

| Model | Size | SHA-256 | License |
| --- | --- | --- | --- |
| `face_detection_yunet_2023mar.onnx` (YuNet) | 232,589 bytes | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | MIT |
| `face_recognition_sface_2021dec.onnx` (SFace) | 38,696,353 bytes | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | Apache 2.0 |

OpenCV Zoo keeps them with Git LFS, and its Hugging Face copies have the same hashes:

```bash
mkdir -p local/models/face
curl -L -o local/models/face/face_detection_yunet_2023mar.onnx https://media.githubusercontent.com/media/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl -L -o local/models/face/face_recognition_sface_2021dec.onnx https://media.githubusercontent.com/media/opencv/opencv_zoo/ba91a3b91d00d76e86540d4013f944bd6b514e39/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

YuNet finds faces at its demo's threshold of 0.9; SFace aligns one face from its five landmarks to 112 x
112 pixels and describes it with 128 values, a length the engine reads from the model when it starts. An
image is decoded from memory by its content; data that is not an image, or that has more than 50 million
pixels, is answered as `invalid`, so the server can tell a refused image from a failed engine. OpenCV's
own messages are limited to errors, so nothing but the protocol reaches standard output. On 2026-11-09,
with OpenCV 5.0.0, YuNet took about 20 ms on a 1280 x 720 frame and 2 ms on the live view's 320-pixel
copy, and SFace about 3 ms per face.

For images from files (H51) the engine sets OpenCV's `OPENCV_IO_MAX_IMAGE_PIXELS` to 50 million before
OpenCV loads, so a file that would decode to more is refused before it is decoded. OpenCV turns a photo
upright by its EXIF orientation as it decodes, and an image whose longer side is above 1920 pixels is
detected on, and returned as a PNG of, a copy scaled down to 1920 (`INTER_AREA`), never up; the replies
give that copy's size as `stored`.

YuNet finds faces of about 10 to 300 pixels (OpenCV Zoo's model notes). When no face is found at the
image's own size, the engine detects on copies whose longer side is 960, 640, 480 and 320 pixels and stops
at the first with a face (H52). A face found on any copy is found again on the image's own pixels: the
region around it is scaled so the face is about 200 pixels wide, never enlarged, and detected once more.
Boxes, landmarks, the alignment and the embedding are then in the image's own pixels (`width`, `height`).
A camera frame whose face is found at its own size is read exactly as before.

## Voice

The voice engine (H54) runs SpeechBrain's ECAPA-TDNN in its own environment, `multimodal-voice`: conda-forge
packages from `environments/voice-win-64.lock`, and SpeechBrain and HyperPyYAML from PyPI, which conda-forge
does not have, pinned by SHA-256 in `environments/voice-pip.txt`:

```bash
conda create -n multimodal-voice --file environments/voice-win-64.lock
conda activate multimodal-voice
python -m pip install --no-deps --only-binary :all: --require-hashes -r environments/voice-pip.txt
python -m pip check
```

The model is [`speechbrain/spkrec-ecapa-voxceleb`](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)
(Apache 2.0) at commit `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`. SpeechBrain's own interface loads its five
files, each pinned by SHA-256; the engine refuses any other file. They are kept in the git-ignored
`local/models/voice`, or in the folder named by `voice_models` in `local/server.toml`:

| File | Size | SHA-256 |
| --- | --- | --- |
| `hyperparams.yaml` | 1,919 bytes | `6f78854fa04ba59e761437b76a2575d3aba5e5016de3e9b69f0c9a5077fb1a41` |
| `embedding_model.ckpt` (the ECAPA-TDNN; its hash is the algorithm's version) | 83,316,686 bytes | `0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2` |
| `mean_var_norm_emb.ckpt` | 1,921 bytes | `cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33` |
| `classifier.ckpt` | 5,534,328 bytes | `fd9e3634fe68bd0a427c95e354c0c677374f62b3f434e45b78599950d860d535` |
| `label_encoder.txt` | 128,619 bytes | `e13c3a167bb4112685670ee896d20e2b565af16b3a4ceeaa8689fa4d22adb8b9` |

```bash
mkdir -p local/models/voice
for f in hyperparams.yaml embedding_model.ckpt mean_var_norm_emb.ckpt classifier.ckpt label_encoder.txt; do
  curl -L -o local/models/voice/$f https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/resolve/0f99f2d0ebe89ac095bcc5903c4dd8f72b367286/$f
done
```

The engine loads the files where they are (`LocalStrategy.NO_LINK`, with the Hugging Face hub offline), so
the folder stays as downloaded and no network is used. It reads a WAV of 16 kHz, one channel and 16-bit PCM
from memory with libsndfile, measures what the checks need (the length, the seconds of speech that stand 15
dB above the recording's quietest tenth, and the share of clipped samples) and computes the embedding of
the whole recording as SpeechBrain's `verify_batch` does (`encode_batch`, `normalize=False`); its 192 values
are read from the model when the engine starts. PyTorch splits ECAPA's sums by its number of threads, so the
engine always uses eight: with a fixed number, a recording gives exactly the same values in every run and in
every process (measured on 2026-11-11). A five-second recording takes about 0.15 s. The measurements need
numpy alone; PyTorch and SpeechBrain load only when the engine starts.

## Tests

```bash
# PY: the research project environment's python.exe, with its folders on PATH
PY -m pytest engines -p no:cacheprovider
```

Synthetic ridge images only. The OpenCV SIFT tests need the research checkout
of `local/research.toml`; the NFIQ 2 test needs the library, named by
`MBS_NFIQ2_BIN` or `nfiq2_bin` in `local/server.toml`. The face tests
(`test_face.py`) use synthetic images without a face: they start the engine in the `multimodal-face`
environment beside the research one (or `MBS_FACE_PYTHON`) with the models of `local/models/face` (or
`MBS_FACE_MODELS`); faces themselves are tried on the camera by hand. The voice tests (`test_voice.py`) use
synthetic recordings, tones in bursts over noise and silence: they test the measurements in any environment
and start the engine in the `multimodal-voice` environment (or `MBS_VOICE_PYTHON`) with the model of
`local/models/voice` (or `MBS_VOICE_MODELS`); voices themselves are tried on the microphones by hand. Tests
whose requirements are missing are skipped.
