from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

from image2pgn.dataset import (
    _class_name_from_dataset_label,
    import_class_folder_dataset,
    make_dataset_from_hf_yolo_zips,
    make_dataset_from_labeled_board,
)


def test_make_dataset_from_labeled_board(tmp_path: Path):
    fen = "8/8/3k4/8/3P4/8/8/4K3"
    image_path = tmp_path / "board.png"
    dataset_dir = tmp_path / "dataset"
    _draw_synthetic_board(image_path, fen)

    count = make_dataset_from_labeled_board(image_path, fen, dataset_dir, split="train")

    assert count == 64
    assert len(list((dataset_dir / "train" / "empty").glob("*.png"))) == 61
    assert len(list((dataset_dir / "train" / "white_pawn").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "white_king").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "black_king").glob("*.png"))) == 1


def test_make_dataset_from_hf_yolo_zip(tmp_path: Path):
    zip_path = tmp_path / "hf.zip"
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    image[:] = (200, 200, 200)
    ok, encoded = cv2.imencode(".png", image)
    assert ok

    with ZipFile(zip_path, "w") as archive:
        archive.writestr("chess_yolo_data/images/train/pos_000000.png", encoded.tobytes())
        archive.writestr(
            "chess_yolo_data/labels/train/pos_000000.txt",
            "5 0.562500 0.937500 0.125000 0.125000\n"
            "11 0.562500 0.062500 0.125000 0.125000\n",
        )

    dataset_dir = tmp_path / "dataset"
    counts = make_dataset_from_hf_yolo_zips(
        [zip_path],
        dataset_dir,
        max_train_images=1,
        empty_per_board=3,
    )

    assert counts["train_boards"] == 1
    assert counts["train_crops"] == 5
    assert len(list((dataset_dir / "train" / "white_king").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "black_king").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "empty").glob("*.png"))) == 3


def test_import_class_folder_dataset_maps_aliases(tmp_path: Path):
    input_dir = tmp_path / "kaggle"
    for folder in ("White Pawn", "black-queen"):
        class_dir = input_dir / folder
        class_dir.mkdir(parents=True)
        for index in range(2):
            image = np.zeros((20, 20, 3), dtype=np.uint8)
            cv2.imwrite(str(class_dir / f"{index}.png"), image)

    dataset_dir = tmp_path / "dataset"
    counts = import_class_folder_dataset(input_dir, dataset_dir, val_ratio=0.5, seed=1)

    assert counts["white_pawn"] == 2
    assert counts["black_queen"] == 2
    assert len(list((dataset_dir / "train" / "white_pawn").glob("*.png"))) == 1
    assert len(list((dataset_dir / "val" / "white_pawn").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "black_queen").glob("*.png"))) == 1
    assert len(list((dataset_dir / "val" / "black_queen").glob("*.png"))) == 1


def test_import_class_folder_dataset_infers_color_from_type_folder(tmp_path: Path):
    input_dir = tmp_path / "kaggle"
    bishop_dir = input_dir / "bishop"
    bishop_dir.mkdir(parents=True)
    white = np.full((20, 20, 3), 220, dtype=np.uint8)
    black = np.full((20, 20, 3), 40, dtype=np.uint8)
    cv2.imwrite(str(bishop_dir / "white.png"), white)
    cv2.imwrite(str(bishop_dir / "black.png"), black)

    dataset_dir = tmp_path / "dataset"
    counts = import_class_folder_dataset(input_dir, dataset_dir, infer_color_from_image=True)

    assert counts["white_bishop"] == 1
    assert counts["black_bishop"] == 1
    assert len(list((dataset_dir / "train" / "white_bishop").glob("*.png"))) == 1
    assert len(list((dataset_dir / "train" / "black_bishop").glob("*.png"))) == 1


def test_class_name_from_dataset_label_maps_chessvision_labels():
    names = ["bB", "bK", "wP", "xx"]

    assert _class_name_from_dataset_label(0, names) == "black_bishop"
    assert _class_name_from_dataset_label(1, names) == "black_king"
    assert _class_name_from_dataset_label(2, names) == "white_pawn"
    assert _class_name_from_dataset_label(3, names) == "empty"


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
