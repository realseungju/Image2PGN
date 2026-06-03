from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from random import Random

import cv2
import numpy as np

from .pieces import CLASS_NAMES


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
PIECE_CLASSES = [class_name for class_name in CLASS_NAMES if class_name != "empty"]

STYLE_COLORS = {
    "chesscom_green": ((238, 238, 210), (118, 150, 86), (246, 246, 105)),
    "chesscom_brown": ((240, 217, 181), (181, 136, 99), (246, 246, 105)),
    "lichess_brown": ((196, 164, 132), (157, 117, 83), (205, 210, 106)),
    "lichess_blue": ((222, 227, 230), (140, 162, 173), (170, 187, 92)),
    "lichess_gray": ((216, 216, 216), (165, 165, 165), (190, 190, 80)),
}

CLASS_WEIGHTS = {
    "empty": 34,
    "white_pawn": 8,
    "black_pawn": 8,
    "white_knight": 2,
    "black_knight": 2,
    "white_bishop": 2,
    "black_bishop": 2,
    "white_rook": 2,
    "black_rook": 2,
    "white_queen": 1,
    "black_queen": 1,
    "white_king": 1,
    "black_king": 1,
}


@dataclass(frozen=True)
class SyntheticConfig:
    out_dir: Path
    sprites_dir: Path
    positions: int = 5000
    split: str = "train"
    styles: tuple[str, ...] = ("chesscom_green", "lichess_brown")
    square_size: int = 96
    seed: int = 42
    coords_probability: float = 0.45
    highlight_probability: float = 0.18
    progress_every: int = 250


@dataclass(frozen=True)
class Sprite:
    image: np.ndarray
    mask: np.ndarray


def generate_synthetic_dataset(config: SyntheticConfig) -> dict[str, int]:
    rng = Random(config.seed)
    sprites = _load_sprites(config.sprites_dir)
    counts: dict[str, int] = defaultdict(int)
    class_choices = list(CLASS_WEIGHTS)
    weights = [CLASS_WEIGHTS[class_name] for class_name in class_choices]

    for board_index in range(config.positions):
        style = rng.choice(config.styles)
        use_coords = rng.random() < config.coords_probability
        highlighted = _highlighted_cells(rng) if rng.random() < config.highlight_probability else set()
        black_orientation = rng.random() < 0.5

        for row in range(8):
            for col in range(8):
                class_name = rng.choices(class_choices, weights=weights, k=1)[0]
                square = _render_square(
                    rng=rng,
                    class_name=class_name,
                    row=row,
                    col=col,
                    style=style,
                    sprites=sprites,
                    square_size=config.square_size,
                    use_coords=use_coords,
                    highlighted=(row, col) in highlighted,
                    black_orientation=black_orientation,
                )
                output_dir = config.out_dir / config.split / class_name
                output_dir.mkdir(parents=True, exist_ok=True)
                counts[class_name] += 1
                output_path = output_dir / f"synth_{style}_{board_index:06d}_{row}_{col}_{counts[class_name]:08d}.png"
                cv2.imwrite(str(output_path), square)
                counts[f"{config.split}_crops"] += 1

        counts[f"{config.split}_boards"] += 1
        if config.progress_every > 0 and (board_index + 1) % config.progress_every == 0:
            print(
                f"{config.split}: generated {board_index + 1}/{config.positions} boards, "
                f"wrote {counts[f'{config.split}_crops']} crops",
                flush=True,
            )

    return dict(counts)


def _load_sprites(sprites_dir: Path) -> dict[str, list[Sprite]]:
    sprites: dict[str, list[Sprite]] = {}
    for class_name in PIECE_CLASSES:
        class_dir = sprites_dir / class_name
        if not class_dir.exists():
            raise FileNotFoundError(f"Missing sprite class directory: {class_dir}")
        class_sprites: list[Sprite] = []
        for path in sorted(class_dir.iterdir()):
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            class_sprites.append(_sprite_from_crop(image))
        if not class_sprites:
            raise ValueError(f"No usable sprite images found in {class_dir}")
        sprites[class_name] = class_sprites
    return sprites


def _sprite_from_crop(image: np.ndarray) -> Sprite:
    image = cv2.resize(image, (96, 96), interpolation=cv2.INTER_AREA)
    bg = _corner_background(image)
    diff = np.linalg.norm(image.astype(np.float32) - bg.astype(np.float32), axis=2)
    mask = np.clip((diff - 10.0) / 55.0, 0.0, 1.0).astype(np.float32)
    mask = cv2.GaussianBlur(mask, (3, 3), 0)
    return Sprite(image=image, mask=mask)


def _corner_background(image: np.ndarray) -> np.ndarray:
    patch = 8
    samples = np.concatenate(
        [
            image[:patch, :patch].reshape(-1, 3),
            image[:patch, -patch:].reshape(-1, 3),
            image[-patch:, :patch].reshape(-1, 3),
            image[-patch:, -patch:].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(samples, axis=0).astype(np.float32)


def _render_square(
    rng: Random,
    class_name: str,
    row: int,
    col: int,
    style: str,
    sprites: dict[str, list[Sprite]],
    square_size: int,
    use_coords: bool,
    highlighted: bool,
    black_orientation: bool,
) -> np.ndarray:
    light, dark, highlight = STYLE_COLORS[style]
    color = light if (row + col) % 2 == 0 else dark
    if highlighted:
        color = _blend_color(color, highlight, 0.55)
    square = np.full((square_size, square_size, 3), color, dtype=np.uint8)

    if class_name != "empty":
        sprite = rng.choice(sprites[class_name])
        scale = rng.uniform(0.82, 1.06)
        offset_x = rng.randint(-4, 4)
        offset_y = rng.randint(-5, 5)
        square = _paste_sprite(square, sprite, scale=scale, offset_x=offset_x, offset_y=offset_y)

    if use_coords:
        _draw_coordinates(square, row, col, black_orientation=black_orientation)

    square = _augment_square(rng, square)
    return square


def _paste_sprite(square: np.ndarray, sprite: Sprite, scale: float, offset_x: int, offset_y: int) -> np.ndarray:
    size = max(12, min(square.shape[0], int(square.shape[0] * scale)))
    image = cv2.resize(sprite.image, (size, size), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(sprite.mask, (size, size), interpolation=cv2.INTER_AREA)

    canvas = square.astype(np.float32)
    x0 = (square.shape[1] - size) // 2 + offset_x
    y0 = (square.shape[0] - size) // 2 + offset_y
    x1 = min(square.shape[1], x0 + size)
    y1 = min(square.shape[0], y0 + size)
    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    x0 = max(0, x0)
    y0 = max(0, y0)
    if x0 >= x1 or y0 >= y1:
        return square

    roi = canvas[y0:y1, x0:x1]
    sprite_roi = image[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)].astype(np.float32)
    mask_roi = mask[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)][..., None]
    canvas[y0:y1, x0:x1] = sprite_roi * mask_roi + roi * (1.0 - mask_roi)
    return np.clip(canvas, 0, 255).astype(np.uint8)


def _draw_coordinates(square: np.ndarray, row: int, col: int, black_orientation: bool) -> None:
    files = "hgfedcba" if black_orientation else "abcdefgh"
    ranks = "12345678" if black_orientation else "87654321"
    text_color = (235, 235, 210) if float(square.mean()) < 145 else (110, 135, 80)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.28
    thickness = 1
    if col == 0:
        cv2.putText(square, ranks[row], (3, 12), font, scale, text_color, thickness, cv2.LINE_AA)
    if row == 7:
        cv2.putText(square, files[col], (square.shape[1] - 13, square.shape[0] - 4), font, scale, text_color, thickness, cv2.LINE_AA)


def _augment_square(rng: Random, square: np.ndarray) -> np.ndarray:
    image = square
    alpha = rng.uniform(0.88, 1.15)
    beta = rng.uniform(-10, 10)
    image = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    if rng.random() < 0.20:
        image = cv2.GaussianBlur(image, (3, 3), 0)
    if rng.random() < 0.20:
        noise = np.random.default_rng(rng.randint(0, 2**31 - 1)).normal(0, 3, image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return image


def _highlighted_cells(rng: Random) -> set[tuple[int, int]]:
    return {
        (rng.randrange(8), rng.randrange(8)),
        (rng.randrange(8), rng.randrange(8)),
    }


def _blend_color(base: tuple[int, int, int], overlay: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return tuple(int(base[i] * (1.0 - alpha) + overlay[i] * alpha) for i in range(3))

