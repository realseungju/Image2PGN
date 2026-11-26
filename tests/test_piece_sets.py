import hashlib
import json

import numpy as np

from image2pgn import cnn, piece_sets


def test_bundled_references_are_consistent():
    references = piece_sets.load_references()
    config = json.loads(piece_sets.CONFIG_PATH.read_text(encoding="utf-8"))
    assert references.vectors.ndim == 2 and len(references.vectors) == len(references.sets) == len(references.pieces)
    assert set(references.sets) == set(config["piece_sets"])
    assert "alpha" not in references.sets  # non-free set stays out of the distribution
    assert set(references.pieces) <= set("PNBRQKpnbrqk")
    assert np.allclose(np.linalg.norm(references.vectors, axis=1), 1, atol=1e-4)
    assert hashlib.sha256(piece_sets.REFERENCE_PATH.read_bytes()).hexdigest() == config["references_sha256"]
    assert references.similarity_cutoff == 0.6892 and references.margin_cutoff == 0.0237


def test_read_board_returns_screen_order_cells():
    board = np.full((640, 640, 3), 200, dtype=np.uint8)
    board[::160, :] = 90
    reading = piece_sets.read_board(board)
    assert len(reading.cells) == 64
    assert reading.occupied == sum(cell != "." for cell in reading.cells)
    assert reading.summary()["accepted"] == reading.accepted


def _reading(cells, accepted=True):
    return piece_sets.PieceSetReading("pixel", "firi", 0.9, 0.1, accepted, tuple(cells), sum(c != "." for c in cells))


def test_routing_keeps_cnn_when_the_set_is_uncertain(monkeypatch):
    cnn_board = [["."] * 8 for _ in range(8)]
    cnn_board[0][0] = "r"
    hints = [{"screen_row": 0, "screen_col": 0, "reason": "low_confidence"}]
    monkeypatch.setattr(piece_sets, "read_board", lambda image: _reading(["."] * 64, accepted=False))
    board, review, summary = cnn._route_piece_set(np.zeros((8, 8, 3), np.uint8), cnn_board, hints)
    assert board is cnn_board and review is hints
    assert summary["strategy"] == "cnn"


def test_routing_uses_piece_set_and_flags_disagreements(monkeypatch):
    cnn_board = [["."] * 8 for _ in range(8)]
    cnn_board[0][0] = "k"          # CNN: king, piece set: pawn -> disagreement
    cnn_board[7][7] = "R"          # both agree
    cells = ["."] * 64
    cells[0], cells[63] = "p", "R"
    hints = [{"screen_row": 7, "screen_col": 7, "reason": "low_confidence"},   # CNN-only hint: dropped
             {"screen_row": 3, "screen_col": 3, "reason": "colored_overlay"}]  # screen hint: kept
    monkeypatch.setattr(piece_sets, "read_board", lambda image: _reading(cells))
    board, review, summary = cnn._route_piece_set(np.zeros((8, 8, 3), np.uint8), cnn_board, hints)
    assert board[0][0] == "p" and board[7][7] == "R"
    assert [(r["screen_row"], r["screen_col"], r["reason"]) for r in review] == [
        (0, 0, "piece_set_disagreement"), (3, 3, "colored_overlay")]
    assert review[0]["class_name"] == "black_king" and review[0]["proposed_class_name"] == "black_pawn"
    assert summary["strategy"] == "piece_set" and summary["disagreements"] == 1
