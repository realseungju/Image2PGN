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

from .board import _best_checker_match, _checker_template_fast, load_image


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


def _refine(gray, candidate, *, resolution=320, padding=.06, step=2):
    # Local search at a bounded resolution; the selected board may use a finer cap.
    x, y, w, h = candidate.bounds
    pad = max(4, round(max(w, h) * padding))
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
    scale = min(1.0, resolution / max(w, h))
    roi = cv2.resize(gray[top:bottom, left:right], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA).astype(np.float32)
    best = candidate
    best_score = -1.0
    # Coordinate descent avoids a quadratic width-by-height template sweep.
    current_w, current_h = round(w * scale), round(h * scale)
    ranges = [range(max(16, round((v - pad) * scale)), min(roi.shape[1-axis], round((v + pad) * scale)) + 1, step) for axis, v in enumerate((w,h))]
    matches = {}
    for _ in range(2):
        for axis in (0,1):
            axis_best = -1.0
            for size in ranges[axis]:
                width, height = (size,current_h) if axis == 0 else (current_w,size)
                key = (width, height)
                if key not in matches:
                    matches[key] = _best_checker_match(roi,width,height,fast_template=True)
                score, (dx,dy) = matches[key]
                if score > axis_best:
                    axis_best, chosen_size = score, size
                if score > best_score:
                    best_score = score
                    bx, by = left + round(dx / scale), top + round(dy / scale)
                    bounds = (bx, by, min(round(width / scale), gray.shape[1] - bx), min(round(height / scale), gray.shape[0] - by))
                    best = BoardCandidate(bounds, float(score))
            if axis == 0:
                current_w = chosen_size
            else:
                current_h = chosen_size
    return best


def find_board_candidates(image: np.ndarray, *, max_candidates: int = 20, min_board_pixels: int = 96, max_search_width: int | None = None, search_step: int = 4, refine: bool = True) -> list[BoardCandidate]:
    """Return diverse proposals in original coordinates, without FEN feedback.

    Stage A only: no full-grid validation, contour ranking, or automatic crop
    replacement. A returned proposal is not proof that a complete board exists.
    """
    if max_candidates < 1 or min_board_pixels < 64:
        raise ValueError("max_candidates must be positive and min_board_pixels >= 64")
    if max_search_width is not None and max_search_width < 64:
        raise ValueError("max_search_width must be >= 64")
    if search_step < 1:
        raise ValueError("search_step must be positive")
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
    if max_search_width is not None:
        targets = sorted(set(min(t, max_search_width) for t in targets))
    for target in targets:
        scale = min(1.0, target / source_w)
        if previous_scale is not None and scale <= previous_scale:
            continue
        work = cv2.resize(gray, (round(source_w * scale), max(1, round(source_h * scale))), interpolation=cv2.INTER_AREA).astype(np.float32)
        lower = max(64, int(np.ceil(min_board_pixels * scale)))
        upper = min(work.shape)
        if previous_scale is not None:
            upper = min(upper, int(np.ceil(72 * scale / previous_scale)))
        for width in range(lower, upper + 1, search_step):
            for aspect in (0.92, 1.0, 1.04):
                height = round(width * aspect)
                if height > work.shape[0]:
                    continue
                scores = np.abs(cv2.matchTemplate(work, _checker_template_fast(width, height), cv2.TM_CCOEFF_NORMED))
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
    if not refine:
        return coarse
    return _distinct([_refine(gray, candidate) for candidate in coarse], max_candidates)


def _corner_matches(gray, side, count):
    """Match the colored tile background while ignoring each tile's center."""
    pattern = _checker_template_fast(side, side)
    position = (np.arange(side) * 8 / side) % 1
    near_corner = ((position >= .10) & (position <= .33)) | ((position >= .67) & (position <= .90))
    mask = np.outer(near_corner, near_corner).astype(np.uint8)
    scores = cv2.matchTemplate(gray, pattern, cv2.TM_CCOEFF_NORMED, mask=mask)
    # Blank patches have zero variance and can produce nonfinite responses.
    np.nan_to_num(scores, copy=False, nan=0, posinf=0, neginf=0)
    scores = np.abs(scores)
    scores[scores > 1.001] = 0
    radius = max(3, side // 3)
    for _ in range(count):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        yield float(score), x, y
        scores[max(0, y-radius):y+radius+1, max(0, x-radius):x+radius+1] = 0


def _refine_corners(gray, candidate):
    x, y, width, height = candidate.bounds
    pad = max(8, round(.045 * max(width, height)))
    left, top = max(0, x-pad), max(0, y-pad)
    right, bottom = min(gray.shape[1], x+width+pad), min(gray.shape[0], y+height+pad)
    region = gray[top:bottom, left:right]
    scale = min(1., 720 / max(region.shape))
    if scale < 1:
        region = cv2.resize(region, (round(region.shape[1] * scale), round(region.shape[0] * scale)),
                            interpolation=cv2.INTER_AREA)
    region = region.astype(np.float32)
    start = max(24, round(max(64, min(width, height) - pad) * scale))
    stop = min(*region.shape, round((max(width, height) + pad) * scale))
    best = candidate
    best_score = -1.0
    for side in range(start, stop + 1, 2):
        score, dx, dy = next(_corner_matches(region, side, 1))
        if score > best_score:
            original_side = min(round(side / scale), right - left, bottom - top)
            refined_x = min(left + round(dx / scale), right - original_side)
            refined_y = min(top + round(dy / scale), bottom - original_side)
            best = BoardCandidate((refined_x, refined_y, original_side, original_side), score, candidate.source)
            best_score = score
    return best


def find_corner_alternatives(image, excluded):
    """Bounded search for a populated board after a larger empty grid won."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x, y, width, height = excluded
    pad = max(4, round(max(width, height) * .018))
    gray[max(0, y-pad):y+height+pad, max(0, x-pad):x+width+pad] = np.median(gray)
    scale = min(1., 400 / max(gray.shape))
    work = cv2.resize(gray, (max(1, round(gray.shape[1]*scale)), max(1, round(gray.shape[0]*scale))),
                      interpolation=cv2.INTER_AREA).astype(np.float32)
    proposals = []
    for side in range(max(24, round(96*scale)), min(*work.shape, round(max(width,height)*scale)) + 1, 4):
        for score, left, top in _corner_matches(work, side, 2):
            if score < .35:
                break
            bounds = tuple(round(value/scale) for value in (left, top, side, side))
            if bounds_iou(bounds, excluded) < .30:
                proposals.append(BoardCandidate(bounds, score, "corner_weighted"))
    refined = []
    for candidate in sorted(proposals, key=lambda c: -c.score):
        if any(bounds_iou(candidate.bounds, previous.bounds) >= .7 for previous in refined):
            continue
        refined.append(_refine_corners(gray, candidate))
        if len(refined) >= 6:
            break
    return _distinct(refined, 5)


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


