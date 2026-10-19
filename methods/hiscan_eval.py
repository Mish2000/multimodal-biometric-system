"""Research methods on HiScan PRO captures (H10).

    python methods/hiscan_eval.py --first FIRST_SET_FOLDER [--session captures/live002] [--fingers 1-10] [--out DIR]

Runs OpenCV SIFT, Pore SIFT and the learned pore descriptor (second training) unchanged from the pinned
research checkout (methods/research-pin.toml), each in its own research environment, on the second capture
set (H9) and the first set. Pairs: (A) placements within the second set, the earlier capture as reference;
(B) the first set as reference against every second-set capture. Every method's pairs are counted against
the plain vs plain thresholds at FAR 0.1 %; pore counts, single-thread timings (the learned descriptor on
the GPU) and template sizes are recorded. Everything written derives from biometric samples, so it goes to
<session>/evaluation (or --out) inside the ignored captures/ folder; that folder must not exist yet.
Run it with the research project environment's Python (local/research.toml).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import research_link

STAGES = ("opencv-sift", "pore-sift", "learned-pore-repeat")
LABELS = {"opencv-sift": "OpenCV SIFT", "pore-sift": "Pore SIFT", "learned-pore-repeat": "Learned pore descriptor"}
SETS = {"A": "second set: placements against each other", "B": "first set (reference) against the second set"}


# ---- plan: images and pairs --------------------------------------------------------------------------------


def parse_fingers(spec: str) -> set[int]:
    fingers = set()
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        fingers.update(range(int(first), int(last or first) + 1))
    if not fingers or not fingers <= set(range(1, 11)):
        raise SystemExit("--fingers takes positions 1-10, for example 1-10 or 1,2")
    return fingers


def first_set_position(name: str) -> int:
    """First-set file names carry _fNN_ for fingers 2-5 and 7-10 and the plain thumb codes _11_ and _12_."""
    match = re.search(r"_f(\d\d)_", name)
    if match:
        return int(match.group(1))
    match = re.search(r"_(11|12)_", name)
    if match:
        return {"11": 1, "12": 6}[match.group(1)]
    raise ValueError(f"no finger position in {name}")


def pair(kind: str, probe: dict, reference: dict) -> dict:
    return {"pair_id": f"{kind}:{probe['image_id']}|{reference['image_id']}", "set": kind,
            "probe_image_id": probe["image_id"], "reference_image_id": reference["image_id"],
            "genuine": probe["finger"] == reference["finger"]}


def build_plan(session: Path, first: Path, fingers: set[int]) -> dict:
    second = []
    for meta in sorted(session.glob("*.json")):
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m["finger_position"] in fingers and m.get("placement"):
            second.append({"image_id": f"{session.name}_f{m['finger_position']:02d}_p{m['placement']}",
                           "path": str((session / m["file"]).resolve()), "set": "second", "finger": m["finger_position"],
                           "placement": m["placement"], "captured_utc": m["captured_utc"]})
    references = []
    for path in sorted(first.glob("*.tif")):
        finger = first_set_position(path.name)
        if finger in fingers:
            references.append({"image_id": f"{path.name.split('_')[0]}_f{finger:02d}", "path": str(path.resolve()),
                               "set": "first", "finger": finger})
    for rows in (second, references):
        if len({r["image_id"] for r in rows}) != len(rows):
            raise SystemExit("two images share an identifier")
    second.sort(key=lambda r: r["captured_utc"])  # ISO 8601 UTC: text order is time order
    pairs = [pair("A", probe, reference) for i, reference in enumerate(second) for probe in second[i + 1:]]
    pairs += [pair("B", probe, reference) for reference in references for probe in second]
    return {"images": second + references, "pairs": pairs}


# ---- stages: each runs inside its research environment ---------------------------------------------------------


def opencv_sift_stage(link: research_link.Link, plan: dict, out: Path) -> dict:
    import cv2
    import fpl3
    from fpl3.algorithms import opencv_sift

    research_link.verify_package(link, fpl3.__file__)
    with open(link.repository / "configs" / "protocol.toml", "rb") as f:
        master_seed = tomllib.load(f)["randomness"]["master_seed"]
    opencv_sift.init_worker(opencv_sift.rng_seed(master_seed))  # one OpenCV thread, FLANN seeded as in the research runs
    features = out / "features" / "opencv-sift"
    features.mkdir(parents=True)
    extraction = [opencv_sift.extract_job((r["image_id"], r["path"], str(features))) for r in plan["images"]]
    comparisons = [opencv_sift.compare_job((p, str(features))) for p in plan["pairs"]]
    return {"versions": {"opencv": cv2.__version__}, "extraction": extraction, "comparisons": comparisons}


def pore_sift_stage(link: research_link.Link, plan: dict, out: Path) -> dict:
    import fpl3
    from fpl3.algorithms import pore_sift

    research_link.verify_package(link, fpl3.__file__)
    with open(link.repository / "configs" / "algorithms.toml", "rb") as f:
        settings = pore_sift.resolve(tomllib.load(f)["pore_sift"], link.repository)
    pore_sift.check_upstream(settings)  # the detector and descriptor checkouts at their pinned revisions
    features, work = out / "features" / "pore-sift", out / "work" / "pore-sift"
    features.mkdir(parents=True)
    images = [{"image_id": r["image_id"], "path": r["path"]} for r in plan["images"]]
    # One worker process with one thread, so the timings are single-thread as in the research.
    extraction, extract_wall = pore_sift.run_parallel("extract", images, 1, settings, features, work)
    comparisons, compare_wall = pore_sift.run_parallel("compare", plan["pairs"], 1, settings, features, work)
    return {"versions": pore_sift.runtime_versions(settings), "extraction": extraction, "comparisons": comparisons,
            "wall_s": {"extract": extract_wall, "compare": compare_wall}}


def learned_stage(link: research_link.Link, plan: dict, out: Path) -> dict:
    import cv2
    import fpl3
    import numpy as np
    import torch
    from fpl3.method import descriptor as d

    research_link.verify_package(link, fpl3.__file__)
    net = d.DescriptionNet(None).to(d.DEVICE)
    net.load_state_dict(torch.load(link.files["learned_descriptor_model"][0], map_location=d.DEVICE))
    pores, features = out / "features" / "pore-sift", out / "features" / "learned-pore-repeat"
    features.mkdir(parents=True)
    sync = torch.cuda.synchronize if d.DEVICE.type == "cuda" else (lambda: None)

    def patches(row: dict) -> np.ndarray:
        image = cv2.imread(row["path"], cv2.IMREAD_GRAYSCALE)
        with np.load(pores / f"{row['image_id']}.npz") as f:  # the pores Pore SIFT detected, as in the research
            return d.image_patches(image, f["points"].astype(int))

    d.describe(net, torch.from_numpy(patches(plan["images"][0])).to(d.DEVICE))  # warm-up, not timed
    sync()
    descriptors, extraction = {}, []
    for row in plan["images"]:
        t0 = time.perf_counter()
        p = patches(row)
        t1 = time.perf_counter()
        desc = d.describe(net, torch.from_numpy(p).to(d.DEVICE)).half()  # float16, as the research stores and scores them
        sync()
        t2 = time.perf_counter()
        path = features / f"{row['image_id']}.npy"
        np.save(path, desc.cpu().numpy())
        descriptors[row["image_id"]] = desc
        extraction.append({"image_id": row["image_id"], "patches": len(p), "patches_s": t1 - t0, "describe_s": t2 - t1,
                           "bytes": path.stat().st_size})
    comparisons = []
    with torch.no_grad():
        for p in plan["pairs"]:
            t0 = time.perf_counter()
            score = d.batched_scores(descriptors[p["probe_image_id"]].float(), [descriptors[p["reference_image_id"]].float()])[0]
            sync()
            comparisons.append({"pair_id": p["pair_id"], "status": "ok", "reason": "", "score": int(score),
                                "compare_s": time.perf_counter() - t0})
    device = torch.cuda.get_device_name(0) if d.DEVICE.type == "cuda" else "cpu"
    return {"versions": {"torch": torch.__version__, "device": device}, "extraction": extraction, "comparisons": comparisons}


STAGE_FUNCTIONS = {"opencv-sift": opencv_sift_stage, "pore-sift": pore_sift_stage, "learned-pore-repeat": learned_stage}


def run_stage(name: str, out: Path) -> None:
    link = research_link.load()
    research_link.verify(link)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    result = STAGE_FUNCTIONS[name](link, plan, out)
    (out / f"{name}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")


# ---- evaluation (standard library only) ------------------------------------------------------------------------


def summary(values: list[float]) -> dict:
    if not values:
        return {}
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def evaluate(plan: dict, results: dict, thresholds: dict) -> dict:
    """Counts at the pinned FAR 0.1 % thresholds. A failed comparison scores 0, the lowest score, and is never
    accepted (the research's E1)."""
    pairs = {p["pair_id"]: p for p in plan["pairs"]}
    second = {r["image_id"] for r in plan["images"] if r["set"] == "second"}
    report = {"methods": {}, "pores": {}, "timing": {}}
    for method in STAGES:
        comparisons = results[method]["comparisons"]
        scores = {c["pair_id"]: (c["score"] if c["status"] == "ok" else 0) for c in comparisons}
        if set(scores) != set(pairs):
            raise SystemExit(f"{method}: the scores do not cover the planned pairs")
        entry = {"failures": sum(c["status"] != "ok" for c in comparisons)}
        for kind in SETS:
            genuine = [scores[i] for i, p in pairs.items() if p["set"] == kind and p["genuine"]]
            impostor = [scores[i] for i, p in pairs.items() if p["set"] == kind and not p["genuine"]]
            if not genuine or not impostor:
                continue
            entry[kind] = {
                "genuine": len(genuine), "impostor": len(impostor),
                "genuine_scores": summary(genuine), "impostor_scores": summary(impostor),
                "margin": min(genuine) - max(impostor),
                "at_far_0.1%": {scenario: {"accept_if_score_above": t, "genuine_accepted": sum(s > t for s in genuine),
                                           "impostor_accepted": sum(s > t for s in impostor)}
                                for scenario, t in thresholds[method].items()},
            }
        report["methods"][method] = entry

    pore_rows = results["pore-sift"]["extraction"]
    for label, keep in (("second", lambda i: i in second), ("first", lambda i: i not in second)):
        report["pores"][label] = summary([r["pores"] for r in pore_rows if keep(r["image_id"])])
    report["pores"]["second_by_image"] = {r["image_id"]: r["pores"] for r in pore_rows if r["image_id"] in second}

    def median_of(rows: list[dict], key: str) -> float:
        return statistics.median(r[key] for r in rows)

    def on_second(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r["image_id"] in second]

    o, ps, ln = (results[m] for m in STAGES)
    detection = median_of(on_second(ps["extraction"]), "detect_s") + median_of(on_second(ps["extraction"]), "nms_s")
    report["timing"] = {
        "note": "medians; extraction on the second-set images; OpenCV SIFT and Pore SIFT on one CPU thread, "
                "the learned descriptor on the GPU after a warm-up; it uses the pores Pore SIFT detects",
        "opencv-sift": {"extract_s": median_of(on_second(o["extraction"]), "extract_s"),
                        "compare_s": median_of(o["comparisons"], "compare_s"),
                        "template_bytes": median_of(on_second(o["extraction"]), "bytes")},
        "pore-sift": {"pore_detection_s": detection, "describe_s": median_of(on_second(ps["extraction"]), "describe_s"),
                      "extract_s": median_of(on_second(ps["extraction"]), "extract_s"),
                      "compare_s": median_of(ps["comparisons"], "compare_s"),
                      "template_bytes": median_of(on_second(ps["extraction"]), "bytes")},
        "learned-pore-repeat": {"pore_detection_s": detection, "patches_s": median_of(on_second(ln["extraction"]), "patches_s"),
                                "describe_s": median_of(on_second(ln["extraction"]), "describe_s"),
                                "extract_s": detection + median_of(on_second(ln["extraction"]), "patches_s")
                                + median_of(on_second(ln["extraction"]), "describe_s"),
                                "compare_s": median_of(ln["comparisons"], "compare_s"),
                                "template_bytes": median_of(on_second(ln["extraction"]), "bytes")},
    }
    for method in STAGES:
        t = report["timing"][method]
        t["one_to_one_s"] = t["extract_s"] + t["compare_s"]  # one new capture against one stored template
    return report


def print_report(report: dict) -> None:
    for kind, title in SETS.items():
        print(f"\n{kind}: {title}")
        for method in STAGES:
            e = report["methods"][method].get(kind)
            if not e:
                continue
            cells = "  ".join(f"{sc} >{v['accept_if_score_above']:g}: genuine {v['genuine_accepted']}/{e['genuine']}, "
                              f"impostor {v['impostor_accepted']}/{e['impostor']}" for sc, v in e["at_far_0.1%"].items())
            print(f"  {LABELS[method]:<24} {cells}  | genuine {e['genuine_scores']}  impostor max {e['impostor_scores']['max']}"
                  f"  margin {e['margin']}")
    print(f"\npores, second set: {report['pores']['second']}; first set: {report['pores']['first']}")
    for method in STAGES:
        t = report["timing"][method]
        print(f"{LABELS[method]:<24} extract {t['extract_s']:.2f} s, compare {1000 * t['compare_s']:.1f} ms, "
              f"1:1 attempt {t['one_to_one_s']:.2f} s, template {t['template_bytes'] / 1024:.0f} KiB")


# ---- driver ------------------------------------------------------------------------------------------------------


def run(args: argparse.Namespace) -> None:
    session = Path(args.session).resolve()
    out = Path(args.out).resolve() if args.out else session / "evaluation"
    captures = (research_link.SYSTEM_ROOT / "captures").resolve()
    if captures not in out.parents:
        raise SystemExit("H10: the results derive from biometric samples and must stay inside the ignored captures/ folder")
    if out.exists():
        raise SystemExit(f"{out} exists already; choose another --out")
    link = research_link.load()
    research_link.verify(link)
    plan = build_plan(session, Path(args.first), parse_fingers(args.fingers))
    counts = {k: sum(p["set"] == k for p in plan["pairs"]) for k in SETS}
    print(f"research {link.commit[:12]} verified; {len(plan['images'])} images, pairs A {counts['A']}, B {counts['B']}")
    out.mkdir(parents=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    pythons = {"opencv-sift": link.project_python, "pore-sift": link.project_python, "learned-pore-repeat": link.gpu_python}
    wall = {}
    for name in STAGES:
        start = time.time()
        subprocess.run([str(pythons[name]), str(Path(__file__).resolve()), "--stage", name, "--out", str(out)],
                       env=research_link.environment(pythons[name]), check=True)
        wall[name] = time.time() - start
        print(f"{LABELS[name]}: done in {wall[name]:.0f} s", flush=True)
    results = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8")) for name in STAGES}
    report = {"decision": "H10", "research_commit": link.commit, "session": session.name, "first_set": Path(args.first).name,
              "pairs": {k: {"genuine": sum(p["set"] == k and p["genuine"] for p in plan["pairs"]),
                            "impostor": sum(p["set"] == k and not p["genuine"] for p in plan["pairs"])} for k in SETS},
              "versions": {name: results[name]["versions"] for name in STAGES}, "stage_wall_s": wall,
              **evaluate(plan, results, link.thresholds)}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print_report(report)
    print(f"\nReport: {out / 'report.json'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--first", help="folder of the first capture set (one TIFF per finger)")
    parser.add_argument("--session", default=str(research_link.SYSTEM_ROOT / "captures" / "live002"))
    parser.add_argument("--fingers", default="1-10")
    parser.add_argument("--out")
    parser.add_argument("--stage", choices=STAGES, help=argparse.SUPPRESS)  # internal: one method in its environment
    args = parser.parse_args(argv)
    if args.stage:
        run_stage(args.stage, Path(args.out))
    elif not args.first:
        parser.error("--first is required")
    else:
        run(args)


if __name__ == "__main__":
    sys.exit(main())
