"""Run every JavaScript check, including the generated-page test, without private data."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from build_label_review import build


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required for JavaScript regression checks.")
    generated_check = root / "tests/test_label_review.cjs"
    checks = sorted(str(p) for p in (root / "tests").glob("*.cjs") if p != generated_check)
    subprocess.run([node, "--test", *checks], cwd=root, check=True)
    work = root / ".tmp"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="js-check-", dir=work) as temporary:
        folder = Path(temporary)
        # A tiny synthetic PNG tests file/checksum and review behavior, not recognition.
        pixels = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")
        source = folder / "synthetic.png"
        source.write_bytes(pixels)
        digest = hashlib.sha256(pixels).hexdigest()
        audit = folder / "audit.json"
        audit.write_text(json.dumps({"items": [
            {"id": f"synthetic-{i}", "kind": "synthetic", "stored_side": "white",
             "path": str(source), "sha256": digest, "used_in_final_replay": True}
            for i in range(50)
        ]}), encoding="utf-8")
        review = folder / "review.html"
        build(audit, root / "infra/label_review.html", review)
        subprocess.run([node, str(generated_check), str(review)], cwd=root, check=True)


if __name__ == "__main__":
    main()
