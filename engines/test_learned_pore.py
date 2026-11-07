"""H39: native half-precision templates and scores equal the pinned descriptor on synthetic images."""

import io
import subprocess

import numpy as np
import pytest

from test_engines import ENGINES, ask, png, research_available, research_link, ridges
import protocol


@pytest.mark.skipif(not research_available(), reason="the pinned research checkout is unavailable")
def test_learned_templates_and_scores_equal_the_research_functions(tmp_path):
    link = research_link.load()
    if not link.gpu_python.exists():
        pytest.skip("the learned descriptor runtime is unavailable")
    coordinates = np.array([[0, 0], [16, 16], [500, 500], [983, 983], [984, 984], [999, 999]], np.int32)
    buffer = io.BytesIO()
    np.savez(buffer, points=coordinates)
    pores = buffer.getvalue()
    (tmp_path / "pores.npz").write_bytes(pores)
    images = [png(ridges(seed=i)) for i in (1, 2)]
    for i, image in enumerate(images):
        (tmp_path / f"{i}.png").write_bytes(image)
    # Independent file-based calls use the same research entry points as H10, not the new adapter.
    expected = tmp_path / "expected.py"
    expected.write_text('''import sys
from pathlib import Path
import cv2, numpy as np, torch
from fpl3.method import descriptor as d
folder, model = Path(sys.argv[1]), sys.argv[2]
net = d.DescriptionNet(None).to(d.DEVICE)
net.load_state_dict(torch.load(model, map_location=d.DEVICE, weights_only=True))
points = np.load(folder / "pores.npz")["points"].astype(int)
templates = []
for i in range(2):
    image = cv2.imread(str(folder / f"{i}.png"), cv2.IMREAD_GRAYSCALE)
    patches = d.image_patches(image, points)
    desc = d.describe(net, torch.from_numpy(patches).to(d.DEVICE)).half()
    np.save(folder / f"{i}.npy", desc.cpu().numpy())
    templates.append(desc)
score = d.batched_scores(templates[1].float(), [templates[0].float()])[0]
(folder / "score.txt").write_text(str(score))
''', encoding="utf-8")
    env = research_link.environment(link.gpu_python)
    subprocess.run([str(link.gpu_python), "-I", "-B", str(expected), str(tmp_path),
                    str(link.files["learned_descriptor_model"][0])], env=env, capture_output=True, check=True, timeout=90)
    engine = subprocess.Popen([str(link.gpu_python), "-I", "-B", str(ENGINES / "learned_pore.py")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, env=env)
    try:
        ready, _ = protocol.read_message(engine.stdout)
        assert ready["ok"] and ready["algorithm"] == "learned-pore" and ready["version"] == link.commit
        templates = []
        for i, image in enumerate(images):
            reply, parts = ask(engine, {"op": "extract"}, [image, pores])
            assert reply["ok"]
            array = np.load(io.BytesIO(parts[0]), allow_pickle=False)
            assert array.dtype == np.float16 and array.shape == (3, 128)
            assert np.array_equal(array, np.load(tmp_path / f"{i}.npy"))
            templates.append(parts[0])
        result, _ = ask(engine, {"op": "compare"}, [templates[1], templates[0]])
        assert result["ok"] and result["score"] == int((tmp_path / "score.txt").read_text())
        empty = io.BytesIO()
        np.save(empty, np.empty((0, 128), np.float16))
        assert ask(engine, {"op": "compare"}, [empty.getvalue(), templates[0]])[0]["score"] == 0
        assert ask(engine, {"op": "extract"}, [images[0]])[0]["ok"] is False
        assert ask(engine, {"op": "extract"}, [png(ridges(size=500)), pores])[0]["ok"] is False
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0
