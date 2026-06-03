import cv2
import numpy as np

from image2pgn.cnn import (
    MultiRootSquareImageDataset,
    class_name_from_prediction,
    class_name_with_inferred_color,
    infer_piece_color_from_square,
)


def test_class_name_from_prediction_keeps_confident_piece():
    assert class_name_from_prediction(["empty", "white_queen"], 1, 0.91, 0.8) == "white_queen"


def test_class_name_from_prediction_drops_low_confidence_to_empty():
    assert class_name_from_prediction(["empty", "white_queen"], 1, 0.41, 0.8) == "empty"


def test_infer_piece_color_from_square_detects_light_foreground():
    square = np.full((80, 80, 3), 40, dtype=np.uint8)
    cv2.circle(square, (40, 40), 18, (230, 230, 230), -1)

    assert infer_piece_color_from_square(square) == "white"


def test_infer_piece_color_from_square_detects_dark_foreground():
    square = np.full((80, 80, 3), 230, dtype=np.uint8)
    cv2.circle(square, (40, 40), 18, (30, 30, 30), -1)

    assert infer_piece_color_from_square(square) == "black"


def test_class_name_with_inferred_color_keeps_piece_type():
    square = np.full((80, 80, 3), 230, dtype=np.uint8)
    cv2.circle(square, (40, 40), 18, (30, 30, 30), -1)

    assert class_name_with_inferred_color(square, "white_queen") == "black_queen"


def test_multi_root_square_image_dataset_reads_all_roots(tmp_path):
    import torch

    for root_name in ("a", "b"):
        class_dir = tmp_path / root_name / "train" / "empty"
        class_dir.mkdir(parents=True)
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        cv2.imwrite(str(class_dir / f"{root_name}.png"), image)

    dataset = MultiRootSquareImageDataset(
        [tmp_path / "a", tmp_path / "b"],
        split="train",
        torch=torch,
    )

    assert len(dataset) == 2
