"""The research's second trained pore descriptor, in its existing runtime (H6, H10, H13, H39).

Pore coordinates come from the shared detector, supplied in memory by the server. The unchanged
research functions select 32 x 32 windows, describe them and compare native float16 NPY templates.
Only the model stays loaded; no capture, coordinates or template survive a request.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "engines"), str(ROOT / "methods")]
ALGORITHM = "learned-pore"


class LearnedPore:
    def __init__(self):
        import fpl3
        import research_link
        import torch
        from fpl3.method import descriptor

        link = research_link.load()
        research_link.verify(link)
        research_link.verify_package(link, fpl3.__file__)
        if not Path(sys.executable).samefile(link.gpu_python):
            raise RuntimeError("the learned descriptor must run in its pinned research environment")
        self.version, self.d, self.torch = link.commit, descriptor, torch
        self.net = descriptor.DescriptionNet(None).to(descriptor.DEVICE)
        self.net.load_state_dict(torch.load(link.files["learned_descriptor_model"][0],
                                            map_location=descriptor.DEVICE, weights_only=True))
        self.net.eval()

    def extract(self, png: bytes, pores: bytes) -> bytes:
        import numpy as np
        pixels = self.d.cv2.imdecode(np.frombuffer(png, np.uint8), self.d.cv2.IMREAD_GRAYSCALE)
        if pixels is None or pixels.shape != (1000, 1000):
            raise ValueError("expected a native 1000 by 1000 fingerprint")
        with np.load(io.BytesIO(pores), allow_pickle=False) as arrays:
            points = arrays["points"]
        if points.ndim != 2 or points.shape[1] != 2 or points.dtype.kind not in "iu" or (points < 0).any() or (points >= 1000).any():
            raise ValueError("invalid pore coordinates")
        patches = self.d.image_patches(pixels, points.astype(int))
        with self.torch.no_grad():
            descriptors = self.d.describe(self.net, self.torch.from_numpy(patches).to(self.d.DEVICE)).half()
        output = io.BytesIO()
        np.save(output, descriptors.cpu().numpy(), allow_pickle=False)
        return output.getvalue()

    def compare(self, probe: bytes, reference: bytes) -> int:
        import numpy as np

        def tensor(data):
            array = np.load(io.BytesIO(data), allow_pickle=False)
            if array.dtype != np.float16 or array.ndim != 2 or array.shape[1] != 128 or not np.isfinite(array).all():
                raise ValueError("invalid native descriptor template")
            return self.torch.from_numpy(array).to(self.d.DEVICE).float()

        with self.torch.no_grad():
            return int(self.d.batched_scores(tensor(probe), [tensor(reference)])[0])


def main():
    import protocol
    with redirect_stdout(sys.stderr):
        method = LearnedPore()

    def extract(_header, parts):
        if len(parts) != 2:
            raise ValueError("extract needs a capture and its shared pore coordinates")
        return {}, method.extract(parts[0], parts[1])

    def compare(_header, parts):
        if len(parts) != 2:
            raise ValueError("compare needs two templates")
        return {"status": "ok", "score": method.compare(parts[0], parts[1])}, b""

    protocol.serve({"algorithm": ALGORITHM, "version": method.version}, {"extract": extract, "compare": compare})


if __name__ == "__main__":
    main()
