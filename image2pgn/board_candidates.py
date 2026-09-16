"""Experimental multiscale board proposals; does not select a production crop.

Run: python -m image2pgn.board_candidates IMAGE --output candidates.json
Scores are checker correlations, not calibrated confidence probabilities.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from .board import _best_checker_match, _checker_template, load_image


@dataclass(frozen=True)
class BoardCandidate:
    bounds: tuple[int, int, int, int]
    score: float
    source: str = "multiscale_checker"


def bounds_iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    intersection = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - intersection
    return float(intersection / union) if union > 0 else 0.0


def _distinct(candidates, limit):
    kept = []
    for candidate in sorted(candidates, key=lambda c: (-c.score, c.bounds)):
        if all(bounds_iou(candidate.bounds, other.bounds) < 0.8 for other in kept):
            kept.append(candidate)
            if len(kept) == limit:
                break
    return kept


def _refine(gray, candidate):
    # Local native-resolution search, capped at 320 pixels per board side.
    x, y, w, h = candidate.bounds
    pad = max(4, round(max(w, h) * 0.06))
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
    scale = min(1.0, 320 / max(w, h))
    roi = cv2.resize(gray[top:bottom, left:right], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA).astype(np.float32)
    best = candidate
    best_score = -1.0
    for width in range(max(16, round((w - pad) * scale)), min(roi.shape[1], round((w + pad) * scale)) + 1, 2):
        for height in range(max(16, round((h - pad) * scale)), min(roi.shape[0], round((h + pad) * scale)) + 1, 2):
            score, (dx, dy) = _best_checker_match(roi, width, height)
            if score > best_score:
                best_score = score
                bx, by = left + round(dx / scale), top + round(dy / scale)
                bounds = (bx, by, min(round(width / scale), gray.shape[1] - bx), min(round(height / scale), gray.shape[0] - by))
                best = BoardCandidate(bounds, float(score))
    return best


def find_board_candidates(image: np.ndarray, *, max_candidates: int = 20, min_board_pixels: int = 96) -> list[BoardCandidate]:
    """Return diverse proposals in original coordinates, without FEN feedback.

    Stage A only: no full-grid validation, contour ranking, or automatic crop
    replacement. A returned proposal is not proof that a complete board exists.
    """
    if max_candidates < 1 or min_board_pixels < 64:
        raise ValueError("max_candidates must be positive and min_board_pixels >= 64")
    if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
        raise ValueError("image must be a nonempty BGR image")
    source_h, source_w = image.shape[:2]
    if min(source_h, source_w) < min_board_pixels:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    proposals = []
    # Larger levels search only sizes too small at the previous level. No upscaling.
    previous_scale = None
    targets = [320, 640]
    final_width = min(source_w, max(640, int(np.ceil(source_w * 64 / min_board_pixels))))
    while targets[-1] < final_width:
        targets.append(min(targets[-1] * 2, final_width))
    for target in targets:
        scale = min(1.0, target / source_w)
        if previous_scale is not None and scale <= previous_scale:
            continue
        work = cv2.resize(gray, (round(source_w * scale), max(1, round(source_h * scale))), interpolation=cv2.INTER_AREA).astype(np.float32)
        lower = max(64, int(np.ceil(min_board_pixels * scale)))
        upper = min(work.shape)
        if previous_scale is not None:
            upper = min(upper, int(np.ceil(72 * scale / previous_scale)))
        for width in range(lower, upper + 1, 4):
            for aspect in (0.92, 1.0, 1.04):
                height = round(width * aspect)
                if height > work.shape[0]:
                    continue
                scores = np.abs(cv2.matchTemplate(work, _checker_template(width, height), cv2.TM_CCOEFF_NORMED))
                for _ in range(3):
                    _, score, _, (x, y) = cv2.minMaxLoc(scores)
                    if score < 0.25:
                        break
                    bx, by = round(x / scale), round(y / scale)
                    bounds = (bx, by, min(round(width / scale), source_w - bx), min(round(height / scale), source_h - by))
                    proposals.append(BoardCandidate(bounds, float(score)))
                    radius = max(1, width // 4)
                    scores[max(0, y-radius):y+radius+1, max(0, x-radius):x+radius+1] = 0
        previous_scale = scale
    coarse = _distinct(proposals, max_candidates)
    return _distinct([_refine(gray, candidate) for candidate in coarse], max_candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = find_board_candidates(load_image(args.image))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema": "board-candidates-v1", "requires_review": True, "candidates": [asdict(c) for c in candidates]}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()


