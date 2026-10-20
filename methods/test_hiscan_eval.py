"""Tests of the H10 evaluation's own logic (no research code, scanner or biometric data needed).

    python -m pytest methods
"""

import json
import subprocess
from pathlib import Path

import pytest

import hiscan_eval
import research_link


def fake_session(folder: Path, fingers=(1, 2), placements=3) -> Path:
    session = folder / "live002"
    session.mkdir()
    minute = 0
    for f in fingers:
        for p in range(1, placements + 1):
            name = f"live002_f{f:02d}_p{p}_x_1"
            (session / f"{name}.png").write_bytes(b"")
            meta = {"file": f"{name}.png", "finger_position": f, "placement": p,
                    "captured_utc": f"2026-10-19T16:{minute:02d}:00.0000000Z"}
            (session / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
            minute += 1
    return session


def fake_first(folder: Path) -> Path:
    first = folder / "live001_plain"
    first.mkdir()
    for name in ("live001_plain_1000_11_right_thumb.tif", "live001_plain_1000_f02_right_index.tif",
                 "live001_plain_1000_12_left_thumb.tif"):
        (first / name).write_bytes(b"")
    return first


def test_first_set_positions():
    assert hiscan_eval.first_set_position("live001_plain_1000_11_right_thumb.tif") == 1
    assert hiscan_eval.first_set_position("live001_plain_1000_12_left_thumb.tif") == 6
    assert hiscan_eval.first_set_position("live001_plain_1000_f10_left_little.tif") == 10
    with pytest.raises(ValueError):
        hiscan_eval.first_set_position("other.tif")


def test_parse_fingers():
    assert hiscan_eval.parse_fingers("1-10") == set(range(1, 11))
    assert hiscan_eval.parse_fingers("1,2,7-8") == {1, 2, 7, 8}
    with pytest.raises(SystemExit):
        hiscan_eval.parse_fingers("0-3")


def test_plan_pairs(tmp_path):
    plan = hiscan_eval.build_plan(fake_session(tmp_path), fake_first(tmp_path), {1, 2})
    a = [p for p in plan["pairs"] if p["set"] == "A"]
    b = [p for p in plan["pairs"] if p["set"] == "B"]
    assert (sum(p["genuine"] for p in a), sum(not p["genuine"] for p in a)) == (6, 9)
    assert (sum(p["genuine"] for p in b), sum(not p["genuine"] for p in b)) == (6, 6)  # the left thumb is not in {1, 2}
    images = {r["image_id"]: r for r in plan["images"]}
    for p in a:  # the earlier capture is the reference, as at enrolment
        assert images[p["reference_image_id"]]["captured_utc"] < images[p["probe_image_id"]]["captured_utc"]
    assert all(images[p["reference_image_id"]]["set"] == "first" for p in b)
    assert {"live001_f01", "live001_f02"} <= set(images)


def test_full_design_counts(tmp_path):
    plan = hiscan_eval.build_plan(fake_session(tmp_path, fingers=range(1, 11)), fake_first(tmp_path), set(range(1, 11)))
    counts = {(p["set"], p["genuine"]) for p in plan["pairs"]}
    assert counts == {("A", True), ("A", False), ("B", True), ("B", False)}
    assert sum(p["set"] == "A" and p["genuine"] for p in plan["pairs"]) == 30
    assert sum(p["set"] == "A" and not p["genuine"] for p in plan["pairs"]) == 405


def test_evaluate_counts_and_failures():
    images = [{"image_id": i, "set": "second"} for i in ("g1", "g2", "x")]
    plan = {"images": images, "pairs": [
        {"pair_id": "A:g2|g1", "set": "A", "genuine": True},
        {"pair_id": "A:x|g1", "set": "A", "genuine": False},
        {"pair_id": "A:x|g2", "set": "A", "genuine": False},
    ]}
    def stage(scores, status=None):
        return {"comparisons": [{"pair_id": k, "status": (status or {}).get(k, "ok"), "score": v, "compare_s": 0.01}
                                for k, v in scores.items()],
                "extraction": [{"image_id": i["image_id"], "pores": 900, "extract_s": 1.0, "detect_s": 0.5, "nms_s": 0.1,
                                "describe_s": 0.2, "patches_s": 0.01, "bytes": 1024} for i in images]}
    results = {
        "opencv-sift": stage({"A:g2|g1": 80, "A:x|g1": None, "A:x|g2": 60}, {"A:x|g1": "failure"}),
        "pore-sift": stage({"A:g2|g1": 21, "A:x|g1": 3, "A:x|g2": 22}),
        "learned-pore-repeat": stage({"A:g2|g1": 40, "A:x|g1": 1, "A:x|g2": 2}),
    }
    thresholds = {"opencv-sift": {"RxJ": 57}, "pore-sift": {"RxJ": 21}, "learned-pore-repeat": {"RxJ": 13}}
    report = hiscan_eval.evaluate(plan, results, thresholds)
    o = report["methods"]["opencv-sift"]
    assert o["failures"] == 1 and o["A"]["impostor_scores"]["min"] == 0  # a failure scores lowest (E1)
    assert o["A"]["at_far_0.1%"]["RxJ"] == {"accept_if_score_above": 57, "genuine_accepted": 1, "impostor_accepted": 1}
    p = report["methods"]["pore-sift"]["A"]["at_far_0.1%"]["RxJ"]
    assert (p["genuine_accepted"], p["impostor_accepted"]) == (0, 1)  # accepted only strictly above the threshold
    assert report["methods"]["learned-pore-repeat"]["A"]["margin"] == 38
    assert report["timing"]["learned-pore-repeat"]["extract_s"] == pytest.approx(0.5 + 0.1 + 0.01 + 0.2)


def test_pin_matches_report_and_rejects_changes(tmp_path):
    repo = tmp_path / "research"
    (repo / "runs").mkdir(parents=True)
    report = {"scenarios": {"RxJ": {"methods": {"m": {"operational": {"0.1%": {"accept_if_score_above": 13.0}}}}}}}
    (repo / "runs" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (repo / "tracked.txt").write_text("a", encoding="utf-8")
    (repo / "AGENTS.md").write_text("a", encoding="utf-8")

    def run(*args):
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True)

    run("init", "-q")
    run("add", "tracked.txt", "AGENTS.md")
    run("commit", "-qm", "pinned")
    commit = research_link.git(repo, "rev-parse", "HEAD")
    branch = research_link.git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    digest = research_link.sha256(repo / "runs" / "report.json")
    pin = tmp_path / "pin.toml"
    pin.write_text(f'[repository]\ncommit = "{commit}"\n[files.plain_thresholds]\npath = "runs/report.json"\n'
                   f'sha256 = "{digest}"\n[thresholds."0.1%"]\nm = {{ RxJ = 13 }}\n', encoding="utf-8")
    local = tmp_path / "local.toml"
    local.write_text(f'repository = "{repo.as_posix()}"\nproject_python = "p"\ngpu_python = "g"\n', encoding="utf-8")
    research_link.verify(research_link.load(pin, local))

    # H21: the documentation may change after the pinned commit, committed or not.
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("b", encoding="utf-8")
    run("add", "AGENTS.md", "docs/note.md")
    run("commit", "-qm", "documentation")
    (repo / "AGENTS.md").write_text("c", encoding="utf-8")
    research_link.verify(research_link.load(pin, local))

    (repo / "tracked.txt").write_text("b", encoding="utf-8")  # a change outside the documentation
    with pytest.raises(research_link.LinkError):
        research_link.verify(research_link.load(pin, local))
    run("commit", "-qam", "code")  # the same change, committed
    with pytest.raises(research_link.LinkError):
        research_link.verify(research_link.load(pin, local))
    run("reset", "-q", "--hard", "HEAD~1")
    run("mv", "tracked.txt", "docs/tracked.txt")  # moved into docs/, it is still gone from where it was
    with pytest.raises(research_link.LinkError):
        research_link.verify(research_link.load(pin, local))
    run("reset", "-q", "--hard", "HEAD")
    run("checkout", "-q", "--orphan", "unrelated")  # the same files in a history without the pinned commit
    run("commit", "-qm", "unrelated")
    with pytest.raises(research_link.LinkError):
        research_link.verify(research_link.load(pin, local))
    run("checkout", "-q", branch)
    research_link.verify(research_link.load(pin, local))

    pin.write_text(pin.read_text(encoding="utf-8").replace("RxJ = 13", "RxJ = 14"), encoding="utf-8")
    with pytest.raises(research_link.LinkError):  # a threshold that is not the report's
        research_link.verify(research_link.load(pin, local))


def test_package_must_come_from_the_checkout(tmp_path):
    link = research_link.Link(tmp_path / "research", "c", {}, {}, Path("p"), Path("g"))
    research_link.verify_package(link, str(tmp_path / "research" / "src" / "fpl3" / "__init__.py"))
    with pytest.raises(research_link.LinkError):
        research_link.verify_package(link, str(tmp_path / "elsewhere" / "fpl3" / "__init__.py"))
