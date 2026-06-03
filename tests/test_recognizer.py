from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from image2pgn.recognizer import learn_templates, recognize_fen


def test_learn_and_recognize_synthetic_board(tmp_path: Path):
    fen = "8/8/3k4/8/3P4/8/8/4K3"
    image_path = tmp_path / "board.png"
    template_dir = tmp_path / "templates"
    _draw_synthetic_board(image_path, fen)

    saved = learn_templates(image_path, fen, template_dir)
    recognized = recognize_fen(image_path, template_dir, threshold=0.75)

    assert saved == 3
    assert recognized == fen


def _draw_synthetic_board(path: Path, fen: str) -> None:
    size = 640
    square = size // 8
    image = np.zeros((size, size, 3), dtype=np.uint8)
    light = (236, 217, 185)
    dark = (174, 137, 104)

    board = _expand(fen)
    for r in range(8):
        for c in range(8):
            color = light if (r + c) % 2 == 0 else dark
            cv2.rectangle(image, (c * square, r * square), ((c + 1) * square, (r + 1) * square), color, -1)
            piece = board[r][c]
            if piece != ".":
                piece_color = (245, 245, 245) if piece.isupper() else (30, 30, 30)
                cv2.putText(
                    image,
                    piece,
                    (c * square + 20, r * square + 58),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    2.0,
                    piece_color,
                    5,
                    cv2.LINE_AA,
                )

    cv2.imwrite(str(path), image)


def _expand(fen: str) -> list[list[str]]:
    rows = []
    for rank in fen.split("/"):
        row = []
        for char in rank:
            if char.isdigit():
                row.extend(["."] * int(char))
            else:
                row.append(char)
        rows.append(row)
    return rows

