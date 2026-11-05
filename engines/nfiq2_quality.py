"""The quality engine (H33): NIST's NFIQ 2.3.0 score of every capture, from memory.

NFIQ 2 is defined for 500 ppi images, so the score is computed on a copy reduced by the mean of every
2x2 block, made here in memory and used for the score only; the methods keep the native 1000 ppi
capture (the research's D1). NFIQ 2 is NIST's v2.3.0 built from source with only NIST's fix for its
C interface (issue 409); see engines/README.md. It runs in the research project environment because
it needs numpy, which the server's environment does not have; it adds no package to it.

    python -I nfiq2_quality.py NFIQ2_BIN      the folder with Nfiq2Api.dll and nist_plain_tir-ink.yaml

Operation (protocol.py):
  quality  data: a PNG -> score (0 to 100), or valid false when NFIQ 2 could not compute one
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT / "engines") not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT / "engines"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import protocol  # noqa: E402

VERSION = "2.3.0"
MODEL_HASH = "b4a1e7586b3be906f9770e4b77768038"  # nist_plain_tir-ink.yaml, the model of NFIQ 2.3
UNKNOWN_FINGER = 0  # NFIQ 2's finger position code when the position is not given


def to_500(image: np.ndarray) -> np.ndarray:
    """The 500 ppi copy: the mean of every 2x2 block, rounded."""
    h, w = image.shape[0] // 2 * 2, image.shape[1] // 2 * 2
    blocks = image[:h, :w].astype(np.float32).reshape(h // 2, 2, w // 2, 2)
    return np.rint(blocks.mean(axis=(1, 3))).astype(np.uint8)


class Nfiq2:
    def __init__(self, folder: Path):
        os.add_dll_directory(str(folder))
        api = ctypes.WinDLL(str(folder / "Nfiq2Api.dll"))
        api.GetNfiq2Version.argtypes = [ctypes.POINTER(ctypes.c_int)] * 3 + [ctypes.POINTER(ctypes.c_char_p)]
        api.InitNfiq2.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        api.InitNfiq2.restype = ctypes.c_char_p
        api.ComputeNfiq2Score.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int]
        api.ComputeNfiq2Score.restype = ctypes.c_int
        major, minor, patch, ocv = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_char_p()
        api.GetNfiq2Version(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch), ctypes.byref(ocv))
        self.version = f"{major.value}.{minor.value}.{patch.value}"
        self.opencv = ocv.value.decode()
        if self.version != VERSION:
            raise RuntimeError(f"NFIQ {self.version} found, {VERSION} expected")
        hash_out = ctypes.c_char_p()
        loaded = api.InitNfiq2(ctypes.byref(hash_out))
        if loaded is None or loaded.decode() != MODEL_HASH:
            raise RuntimeError("NFIQ 2 did not load its 2.3 model; use the build with NIST's fix (engines/README.md)")
        self.model_hash = loaded.decode()
        self.api = api

    def score(self, image_500: np.ndarray) -> int:
        data = np.ascontiguousarray(image_500, dtype=np.uint8)
        return self.api.ComputeNfiq2Score(UNKNOWN_FINGER, data.ctypes.data, data.size, data.shape[1], data.shape[0], 500)


def main() -> None:
    nfiq2 = Nfiq2(Path(sys.argv[1]).resolve())

    def quality(_header: dict, parts: list[bytes]):
        image = cv2.imdecode(np.frombuffer(parts[0], np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("the data is not an image")
        value = nfiq2.score(to_500(image))
        return {"score": value if 0 <= value <= 100 else None, "valid": 0 <= value <= 100, "code": value}, b""

    protocol.serve({"engine": "nfiq2", "version": nfiq2.version, "opencv": nfiq2.opencv,
                    "model_hash": nfiq2.model_hash}, {"quality": quality})


if __name__ == "__main__":
    main()
