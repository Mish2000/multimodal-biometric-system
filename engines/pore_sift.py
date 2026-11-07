"""Pore SIFT in its existing research environment (H10, H13, H38).

The project Python verifies the research pin and resolves its settings once at startup. Python 3.10
then imports the unchanged research worker, detector, NMS, descriptors and basic matcher. The NMS file
outputs are redirected to memory. Native templates keep the research's points/descriptors NPZ layout.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "engines"), str(ROOT / "methods")]
ALGORITHM = "pore-sift"


def verified_settings() -> dict:
    """Executed only in the research project Python, which has tomllib (H10)."""
    import tomllib
    import research_link
    import fpl3
    from fpl3.algorithms import pore_sift

    link = research_link.load()
    research_link.verify(link)
    research_link.verify_package(link, fpl3.__file__)
    with open(link.repository / "configs" / "algorithms.toml", "rb") as source:
        settings = pore_sift.resolve(tomllib.load(source)["pore_sift"], link.repository)
    pore_sift.check_upstream(settings)
    for key in ("survey", "dahia"):
        if research_link.git(Path(settings[f"{key}_dir"]), "diff", "HEAD", "--"):
            raise research_link.LinkError(f"{key} checkout has local changes")
    return {**settings, "repository": str(link.repository), "version": link.commit}


class CoordinateBuffer(io.StringIO):
    def close(self) -> None:
        """Upstream closes its text output; the caller reads that output before releasing the buffer."""


def points_in_memory(up, worker, prediction):
    """Run the exact upstream NMS and coordinate writer, replacing only their output destinations."""
    import numpy as np

    coordinates = CoordinateBuffer()
    original_cv2 = up.entireImage.cv2
    namespace = up.entireImage.writeCoordinates.__globals__
    had_open, original_open = "open" in namespace, namespace.get("open")

    def coordinate_file(path, mode):
        if path != "memory/1.txt" or mode != "w":
            raise ValueError("unexpected NMS output")
        return coordinates

    try:
        up.entireImage.cv2 = types.SimpleNamespace(imwrite=lambda _path, _pixels: True)
        namespace["open"] = coordinate_file
        up.entireImage.apply_nms(prediction, worker.NMS_PROBABILITY, worker.NMS_BOX, worker.NMS_IOU,
                                 "memory/", 1, "memory/", worker.NMS_WINDOW)
        points = [[int(value) for value in line.split(",")] for line in coordinates.getvalue().splitlines() if line.strip()]
        return np.asarray(points, np.int32).reshape(-1, 2)
    finally:
        up.entireImage.cv2 = original_cv2
        if had_open:
            namespace["open"] = original_open
        else:
            namespace.pop("open", None)
        io.StringIO.close(coordinates)


def template_bytes(points, descriptors) -> bytes:
    import numpy as np
    output = io.BytesIO()
    np.savez(output, points=np.asarray(points, np.int32).reshape(-1, 2),
             descriptors=np.asarray(descriptors, np.float32).reshape(-1, 128))
    return output.getvalue()


def from_template(data: bytes):
    import numpy as np
    with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
        return arrays["points"], arrays["descriptors"]


class PoreSift:
    def __init__(self, settings: dict):
        path = Path(settings["repository"]) / "src" / "fpl3" / "algorithms" / "pore_sift_worker.py"
        spec = importlib.util.spec_from_file_location("research_pore_worker", path)
        self.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.worker)
        self.up = self.worker.import_upstream(settings["survey_dir"], settings["dahia_dir"], 1)
        self.model = self.worker.load_detector(self.up, settings["survey_dir"], settings["model_sha256"])
        self.to_tensor = self.up.torchvision.transforms.Compose([self.up.torchvision.transforms.ToTensor()])

    def detect(self, png: bytes):
        import numpy as np
        pixels = self.up.cv2.imdecode(np.frombuffer(png, np.uint8), self.up.cv2.IMREAD_GRAYSCALE)
        if pixels is None or pixels.shape != (1000, 1000):
            raise ValueError("expected a native 1000 by 1000 fingerprint")
        with self.up.torch.no_grad():
            prediction = self.model(self.to_tensor(pixels).unsqueeze(dim=0).float()).detach().cpu()
        points = points_in_memory(self.up, self.worker, prediction)
        return pixels, points

    def extract(self, png: bytes):
        import numpy as np
        pixels, points = self.detect(png)
        # The research's load_image reads gray pixels, casts to float32 and divides by 255.
        image = np.array(pixels, dtype=np.float32) / 255
        descriptors = self.up.dahia_utils.sift_descriptors(image, points.astype(np.float32))
        return points, np.asarray(descriptors, np.float32).reshape(-1, 128)

    def compare(self, probe: bytes, reference: bytes) -> int:
        points1, descriptors1 = from_template(probe)
        points2, descriptors2 = from_template(reference)
        return int(self.up.matching.basic(descriptors1, descriptors2, points1, points2, thr=self.worker.RATIO))


def main(project_python: str) -> None:
    import protocol
    completed = subprocess.run([project_python, "-I", "-B", str(Path(__file__).resolve()), "--settings"],
                               capture_output=True, text=True, check=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    settings = json.loads(completed.stdout)
    if not Path(sys.executable).samefile(settings["python"]):
        raise RuntimeError("Pore SIFT must run in its pinned research environment")
    with redirect_stdout(sys.stderr):
        method = PoreSift(settings)

    def extract(_header, parts):
        points, descriptors = method.extract(parts[0])
        return {"keypoints": len(points)}, template_bytes(points, descriptors)

    def compare(_header, parts):
        if len(parts) != 2:
            raise ValueError("compare needs two templates")
        return {"status": "ok", "score": method.compare(parts[0], parts[1])}, b""

    def detect(_header, parts):
        # H39: one detection can feed either descriptor, without keeping findings between requests.
        import numpy as np
        _, points = method.detect(parts[0])
        output = io.BytesIO()
        np.savez(output, points=points)
        return {"keypoints": len(points)}, output.getvalue()

    protocol.serve({"algorithm": ALGORITHM, "version": settings["version"]},
                   {"extract": extract, "detect": detect, "compare": compare})


if __name__ == "__main__":
    if sys.argv[1:] == ["--settings"]:
        print(json.dumps(verified_settings()))
    else:
        main(sys.argv[1])
