"""Compare screenshot recognition variants on a labeled development collection.

Labels: {"items": [{"file": "1.jpg", "rows": [eight screen-order strings],
"orientation": "white"|"black"}]}. A dot denotes an empty square.
The older visual-labels.json "id" field is also supported (id + ".jpg").
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image2pgn.cnn import recognize_fen_cnn_result
from image2pgn.fen import compress_board, expand_placement, orient_board

VARIANTS = {"baseline": ("legacy", False), "board": ("grid", False),
            "empty": ("legacy", True), "both": ("grid", True)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    args = parser.parse_args()
    manifest = json.loads(args.labels.read_text(encoding="utf-8"))
    prepared = []
    for item in manifest["items"]:
        filename = item.get("file") or f"{item['id']}.jpg"
        path = (args.images / filename).resolve()
        if not path.is_relative_to(args.images.resolve()):
            parser.error("Label image path must remain inside --images.")
        board = [list(row) for row in item["rows"]]
        expected = compress_board(orient_board(board, item["orientation"]))
        expand_placement(expected)  # Validate piece symbols as well as shape.
        prepared.append((filename, path, expected, hashlib.sha256(path.read_bytes()).hexdigest()))
    if not prepared or len({name for name, *_ in prepared}) != len(prepared):
        parser.error("Labels must contain unique, nonempty image filenames.")
    args.out.mkdir(parents=True, exist_ok=True)
    metadata = {"purpose": "development regression, not held-out performance",
                "label_method": manifest.get("label_method", "provided labels; not independently verified"),
                "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
                "labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
                "threshold": args.threshold, "device": args.device,
                "orientation": "auto", "results": []}
    for mode in args.variants:
        detector, suppress = VARIANTS[mode]
        for filename, path, expected, digest in prepared:
            started = time.perf_counter()
            with redirect_stdout(io.StringIO()):
                result = recognize_fen_cnn_result(path, args.model, orientation="auto",
                    device=args.device, threshold=args.threshold, board_detector=detector,
                    suppress_empty_background=suppress, debug_dir=args.out / mode / path.stem)
            truth, prediction = expand_placement(expected), expand_placement(result.placement)
            errors = [{"square": f"{'abcdefgh'[c]}{8-r}", "expected": truth[r][c], "predicted": prediction[r][c]}
                      for r in range(8) for c in range(8) if truth[r][c] != prediction[r][c]]
            row = {"mode": mode, "file": filename, "source_sha256": digest, "expected": expected,
                   "placement": result.placement, "orientation": result.orientation,
                   "correct": 64-len(errors), "errors": errors,
                   "seconds": round(time.perf_counter()-started, 3)}
            metadata["results"].append(row)
            (args.out / "results.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            print(f"{mode} {filename}: {row['correct']}/64", flush=True)
    for mode in args.variants:
        rows = [r for r in metadata["results"] if r["mode"] == mode]
        print(f"{mode}: exact={sum(r['correct']==64 for r in rows)}/{len(rows)} squares={sum(r['correct'] for r in rows)}/{64*len(rows)}")


if __name__ == "__main__":
    main()
