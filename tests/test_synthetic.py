from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from image2pgn.pieces import CLASS_NAMES
from image2pgn.synthetic import SyntheticConfig, generate_synthetic_dataset


def test_generate_synthetic_dataset(tmp_path: Path):
    sprites = tmp_path / "sprites"
    for class_name in CLASS_NAMES:
        if class_name == "empty":
            continue
        class_dir = sprites / class_name
        class_dir.mkdir(parents=True)
        image = np.full((32, 32, 3), 200 if class_name.startswith("white") else 45, dtype=np.uint8)
        cv2.circle(image, (16, 16), 8, (250, 250, 250) if class_name.startswith("white") else (20, 20, 20), -1)
        cv2.imwrite(str(class_dir / "sprite.png"), image)

    out = tmp_path / "dataset"
    counts = generate_synthetic_dataset(
        SyntheticConfig(
            out_dir=out,
            sprites_dir=sprites,
            positions=2,
            split="train",
            styles=("chesscom_green",),
            square_size=48,
            seed=1,
            progress_every=0,
        )
    )

    assert counts["train_boards"] == 2
    assert counts["train_crops"] == 128
    assert len(list((out / "train").rglob("*.png"))) == 128

