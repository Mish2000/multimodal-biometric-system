"""Pore CNN, the research's trained pore network, in its existing runtime (H6, H10, H13, H39, H44).

Pore coordinates come from the shared detector, supplied in memory by the server. The unchanged
research functions select 32 x 32 windows, describe them and compare native float16 NPY templates.
Only the model stays loaded; no capture, coordinates or template survive a request.

A template holds descriptors only. For an illustration (H44) the server also sends the pores that each
template was described from; the research's own window selection maps descriptor rows back to them.
"""

from __future__ import annotations

import io
import math
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
            raise RuntimeError("Pore CNN must run in its pinned research environment")
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

    def tensor(self, data: bytes):
        import numpy as np
        array = np.load(io.BytesIO(data), allow_pickle=False)
        if array.dtype != np.float16 or array.ndim != 2 or array.shape[1] != 128 or not np.isfinite(array).all():
            raise ValueError("invalid native descriptor template")
        return self.torch.from_numpy(array).to(self.d.DEVICE).float()

    def compare(self, probe: bytes, reference: bytes) -> int:
        with self.torch.no_grad():
            return int(self.d.batched_scores(self.tensor(probe), [self.tensor(reference)])[0])

    def described_points(self, pores: bytes):
        """H44: the pores whose windows the research describes, in template row order, as x and y.

        The research's image_patches runs unchanged on an image whose pixels hold their own positions,
        so the centre of every returned window names the pore it was cut around."""
        import numpy as np
        with np.load(io.BytesIO(pores), allow_pickle=False) as arrays:
            points = arrays["points"]
        if points.ndim != 2 or points.shape[1] != 2 or points.dtype.kind not in "iu" or (points < 0).any() or (points >= 1000).any():
            raise ValueError("invalid pore coordinates")
        positions = np.arange(1000 * 1000, dtype=np.int32).reshape(1000, 1000)
        windows = self.d.image_patches(positions, points.astype(int))
        centres = windows[:, self.d.PATCH // 2, self.d.PATCH // 2].astype(np.int64)
        return np.column_stack((centres % 1000, centres // 1000)).astype("<f4")

    def counted_pairs(self, probe, reference):
        """H44: the probe and reference rows that batched_scores counts, by the same operations.

        One reference forms one group of width len(reference); one descriptor on either side uses
        basic_score's single-descriptor rule, as batched_scores does."""
        torch, ratio = self.torch, self.d.RATIO
        n, m = len(probe), len(reference)
        if n == 0 or m == 0:
            empty = torch.zeros(0, dtype=torch.long)
            return empty, empty
        rows = torch.arange(n, device=probe.device)
        if n == 1 or m == 1:
            d = (probe * probe).sum(1)[:, None] - 2 * probe @ reference.T + (reference * reference).sum(1)[None, :]
            j = d.argmin(1)
            keep = d.argmin(0)[j] == rows
            return rows[keep].cpu(), j[keep].cpu()
        padded = torch.zeros((1, m, probe.shape[1]), dtype=probe.dtype, device=probe.device)
        padded[0] = reference
        d = torch.matmul(probe.unsqueeze(0), padded.transpose(1, 2))
        d.mul_(-2).add_((probe * probe).sum(1)[None, :, None]).add_((padded * padded).sum(-1)[:, None, :])
        row_best, j = d.min(dim=2)
        d.scatter_(2, j.unsqueeze(2), math.inf)
        row_second = d.min(dim=2).values
        d.scatter_(2, j.unsqueeze(2), row_best.unsqueeze(2))
        best_row = d.min(dim=1).indices
        d.scatter_(1, best_row.unsqueeze(1), math.inf)
        column_second = d.min(dim=1).values
        keep = ((torch.gather(best_row, 1, j) == rows[None, :]) & (row_best < ratio * row_second)
                & (row_best < ratio * torch.gather(column_second, 1, j)))[0]
        return rows[keep].cpu(), j[0][keep].cpu()

    def compare_with_pairs(self, probe: bytes, reference: bytes, probe_pores: bytes,
                           reference_pores: bytes) -> tuple[int, bytes]:
        """H44: the research score decides; the pairs must count exactly that score."""
        import numpy as np
        first, second = self.tensor(probe), self.tensor(reference)
        with self.torch.no_grad():
            score = int(self.d.batched_scores(first, [second])[0])
            probe_rows, reference_rows = self.counted_pairs(first, second)
        if len(probe_rows) != score:
            raise ValueError("the counted pairs do not agree with the research score")
        probe_points, reference_points = self.described_points(probe_pores), self.described_points(reference_pores)
        if len(probe_points) != len(first) or len(reference_points) != len(second):
            raise ValueError("the pore coordinates do not belong to these templates")
        pairs = np.column_stack((probe_points[probe_rows.numpy()], reference_points[reference_rows.numpy()]))
        return score, pairs.astype("<f4").reshape(-1, 4).tobytes()


def main():
    import protocol
    with redirect_stdout(sys.stderr):
        method = LearnedPore()

    def extract(_header, parts):
        if len(parts) != 2:
            raise ValueError("extract needs a capture and its shared pore coordinates")
        return {}, method.extract(parts[0], parts[1])

    def compare(_header, parts):
        if _header.get("view") is True:
            if len(parts) != 4:
                raise ValueError("a viewed comparison needs two templates and the pores they were described from")
            score, pairs = method.compare_with_pairs(*parts)
            return {"status": "ok", "score": score, "matches": len(pairs) // 16}, pairs
        if len(parts) != 2:
            raise ValueError("compare needs two templates")
        return {"status": "ok", "score": method.compare(parts[0], parts[1])}, b""

    protocol.serve({"algorithm": ALGORITHM, "version": method.version}, {"extract": extract, "compare": compare})


if __name__ == "__main__":
    main()
