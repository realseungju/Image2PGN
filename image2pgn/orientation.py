"""Coordinate evidence first; explicit, fallible position-based fallback."""
from pathlib import Path
import json
import os
import subprocess
import tempfile

import chess
import cv2
import numpy as np

from .fen import expand_placement, score_piece_placement


def coordinate_decision(observations):
    votes = {"white": set(), "black": set()}
    for observation in observations:
        axis = observation["axis"]
        index = observation["index"]
        char = observation["text"].lower()
        if axis not in ("file", "rank") or not 0 <= index < 8:
            continue
        forward = "abcdefgh" if axis == "file" else "87654321"
        for direction, sequence in (("white", forward), ("black", forward[::-1])):
            if char == sequence[index]:
                votes[direction].add((axis, index))
    if votes["white"] and votes["black"]:
        return None, "conflicting_coordinates"
    for direction in ("white", "black"):
        if any(sum(a == axis for a, _ in votes[direction]) >= 3 for axis in ("file", "rank")):
            return direction, "consistent_coordinates"
    return None, "insufficient_coordinates"


def position_estimate(white, black):
    scores, valid, pawn_counts = {}, {}, {}
    for direction, placement in (("white", white), ("black", black)):
        board = expand_placement(placement)
        terms = [
            row_index - 3.5 if piece == "P" else 3.5 - row_index
            for row_index, row in enumerate(board)
            for piece in row if piece in "Pp"
        ]
        # A weak home-side prior, never a rule that advanced pawns are illegal.
        scores[direction] = float(score_piece_placement(placement)) + (
            4 * sum(terms) / len(terms) if terms else 0
        )
        pawn_counts[direction] = len(terms)
        # Side to move is unknown; either side must be allowed by this check.
        valid[direction] = any(
            chess.Board(placement + " " + turn + " - - 0 1").is_valid()
            for turn in ("w", "b")
        )
    if valid["white"] != valid["black"]:
        chosen = "white" if valid["white"] else "black"
        reason = "one_orientation_has_valid_position"
    else:
        chosen = "black" if scores["black"] > scores["white"] else "white"
        reason = "pawn_distribution_and_back_rank_prior"
    uncertain = valid["white"] == valid["black"] and (
        not valid["white"] or pawn_counts["white"] < 2
        or abs(scores["white"] - scores["black"]) < 3
    )
    return {
        "orientation": chosen, "source": "position",
        "status": "uncertain" if uncertain else "estimated", "scores": scores,
        "valid_for_some_turn": valid, "reason": reason,
        "candidates": {"white": white, "black": black},
    }


def _coordinate_strips(board_image):
    board = cv2.resize(board_image, (640, 640), interpolation=cv2.INTER_AREA)
    strips = {}
    # Current adapter supports inside-left ranks and inside-bottom-right files.
    # Separate labels from pieces and normalize either text polarity. Other
    # layouts safely fall back when they provide no consistent evidence.
    for axis in ("rank", "file"):
        patches = []
        for index in range(8):
            patch = (board[index * 80:index * 80 + 22, :17] if axis == "rank"
                     else board[-22:, index * 80 + 60:(index + 1) * 80])
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if np.median(gray) == 0:
                gray = 255 - gray
            gray = cv2.resize(gray, (60, 66), interpolation=cv2.INTER_CUBIC)
            patches.append(cv2.copyMakeBorder(
                gray, 20, 20, 70, 70, cv2.BORDER_CONSTANT, value=255
            ))
        strips[axis] = np.hstack(patches)
    return strips


def read_coordinates(board_image):
    if os.name != "nt":
        return [], "Windows OCR unavailable on this platform"
    try:
        script = Path(__file__).with_name("windows_ocr.ps1").read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [], str(exc)
    # Execute fixed local code directly; do not change execution policy.
    observations, errors = [], []
    with tempfile.TemporaryDirectory(prefix="chess-coordinates-") as tmp:
        for axis, strip in _coordinate_strips(board_image).items():
            path = Path(tmp) / (axis + ".png")
            env = os.environ.copy()
            env["CHESS_OCR_IMAGE_PATH"] = str(path.resolve())
            try:
                if not cv2.imwrite(str(path), strip):
                    raise OSError("Could not write coordinate image")
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", script],
                    env=env, capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:])
                payload = json.loads(result.stdout.decode("utf-8-sig"))
                for word in payload["words"]:
                    text = word["text"].strip().strip("|").lower()
                    alphabet = "abcdefgh" if axis == "file" else "12345678"
                    if len(text) != 1 or text not in alphabet:
                        continue
                    index = int((word["x"] + word["width"] / 2) // 200)
                    if 0 <= index < 8:
                        observations.append({"axis": axis, "index": index, "text": text})
            except (OSError, ValueError, KeyError, TypeError, RuntimeError,
                    subprocess.TimeoutExpired) as exc:
                errors.append(axis + ": " + str(exc))
    return observations, "; ".join(errors) or None


def resolve_orientation(white, black, board_image=None, observations=None):
    estimate = position_estimate(white, black)
    error = None
    if observations is None:
        observations, error = (read_coordinates(board_image)
                               if board_image is not None else ([], None))
    coordinate, reason = coordinate_decision(observations)
    estimate.update(coordinate_observations=observations, coordinate_reason=reason, ocr_error=error)
    if coordinate:
        estimate.update(orientation=coordinate, source="coordinates",
                        status="coordinate_supported", reason=reason)
    return estimate
