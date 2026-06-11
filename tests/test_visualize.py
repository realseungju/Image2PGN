from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from image2pgn.analyze import MoveAnalysis, PositionAnalysis
from image2pgn.visualize import _square_center, save_analysis_overlay


def test_square_center_maps_white_and_black_orientation():
    assert _square_center("a1", "white", 80) == (40, 600)
    assert _square_center("a1", "black", 80) == (600, 40)


def test_save_analysis_overlay_creates_png(tmp_path: Path):
    image_path = tmp_path / "board.png"
    image = np.full((640, 640, 3), 180, dtype=np.uint8)
    cv2.imwrite(str(image_path), image)
    output_path = tmp_path / "overlay.png"
    analysis = PositionAnalysis(
        fen="8/8/8/8/8/8/8/4K2k w - - 0 1",
        legal=True,
        turn="white",
        side_to_move="White",
        evaluation="+0.10",
        evaluation_cp=10,
        mate=None,
        summary="A simple test position.",
        moves=[
            MoveAnalysis(
                rank=1,
                move_uci="e1e2",
                san="Ke2",
                score="+0.10",
                score_cp=10,
                mate=None,
                delta="best-eval",
                delta_cp=0,
                pv_san=["Ke2"],
                themes=["improves king safety"],
            )
        ],
        threats=["No immediate tactical issue in this fixture."],
        warnings=[],
    )

    save_analysis_overlay(image_path, analysis, "white", output_path)

    assert output_path.exists()
    assert cv2.imread(str(output_path)) is not None

