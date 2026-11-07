"""A stand-in for `ScannerCapture oem-acquire` (H33) in the tests: each run takes the next step of a JSON script
and answers on standard output exactly as the scanner tool does. Its "captures" are labels, never images.

    python fake_scanner.py --script FILE --wait finger|lift --timeout-s N
Steps: {"wait": "finger", "image": "q64:A"}, {"wait": "lift"}, {"exit": 2, "stderr": "..."}, {"exit": 3},
{"hang": true} (waits until it is stopped).
"""

import json
import sys
import time
from pathlib import Path

args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
script = Path(args["--script"])
steps = json.loads(script.read_text(encoding="utf-8"))
step = steps.pop(0) if steps else {"exit": 9, "stderr": "the fake scanner has no step left"}
script.write_text(json.dumps(steps), encoding="utf-8")
log = script.with_suffix(".log")
log.write_text(log.read_text(encoding="utf-8") + args["--wait"] + "\n" if log.exists() else args["--wait"] + "\n",
               encoding="utf-8")
out = sys.stdout.buffer


def send(header: dict, data: bytes = b"") -> None:
    out.write(json.dumps(header, separators=(",", ":")).encode() + b"\n" + data)
    out.flush()


if step.get("hang"):
    send({"event": "ready", "wait": args["--wait"], "ppi": 1000})
    if not step.get("ignore_cancel"):
        sys.stdin.buffer.read()
        script.with_suffix(".closed").write_text("native cleanup", encoding="utf-8")
        sys.exit(4)
    time.sleep(120)
    sys.exit(0)
if "exit" in step:
    sys.stderr.write(step.get("stderr", ""))
    if step["exit"] == 3:
        send({"event": "ready", "wait": args["--wait"], "ppi": 1000})
        send({"event": "timeout", "frames": 2})
    sys.exit(step["exit"])
if step["wait"] != args["--wait"]:
    sys.stderr.write(f"expected --wait {step['wait']}, got {args['--wait']}")
    sys.exit(9)
send({"event": "ready", "wait": step["wait"], "ppi": 1000})
if step["wait"] == "lift":
    send({"event": "frame", "finger": True})
    send({"event": "lifted", "frames": 3})
else:
    send({"event": "frame", "kept": False, "checks": [{"name": "ridge texture", "passed": False, "detail": "empty"}]})
    # A local check may hand a stored capture instead (tests/test_fingerprint_live.py).
    image = Path(step["file"]).read_bytes() if "file" in step else b"FAKEPNG:" + step["image"].encode()
    checks = [{"name": name, "passed": True, "detail": "ok"} for name in ("size", "resolution", "ridge texture", "fine detail")]
    send({"event": "image", "width": 1000, "height": 1000, "ppi": 1000, "checks": checks, "length": len(image)}, image)
