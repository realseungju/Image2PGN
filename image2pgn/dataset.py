from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from random import Random
from zipfile import ZipFile

import cv2
import numpy as np

from .board import load_image, save_debug_board, split_squares, warp_board
from .fen import expand_placement, orient_board
from .pieces import CLASS_NAMES, class_name_for_piece


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

CLASS_ALIASES = {
    "empty": "empty",
    "blank": "empty",
    "none": "empty",
    "xx": "empty",
    "whitepawn": "white_pawn",
    "whitepawns": "white_pawn",
    "white_pawn": "white_pawn",
    "white-pawn": "white_pawn",
    "wp": "white_pawn",
    "whiteknight": "white_knight",
    "whiteknights": "white_knight",
    "white_knight": "white_knight",
    "white-knight": "white_knight",
    "wn": "white_knight",
    "whitebishop": "white_bishop",
    "whitebishops": "white_bishop",
    "white_bishop": "white_bishop",
    "white-bishop": "white_bishop",
    "wb": "white_bishop",
    "whiterook": "white_rook",
    "whiterooks": "white_rook",
    "white_rook": "white_rook",
    "white-rook": "white_rook",
    "wr": "white_rook",
    "whitequeen": "white_queen",
    "whitequeens": "white_queen",
    "white_queen": "white_queen",
    "white-queen": "white_queen",
    "wq": "white_queen",
    "whiteking": "white_king",
    "whitekings": "white_king",
    "white_king": "white_king",
    "white-king": "white_king",
    "wk": "white_king",
    "blackpawn": "black_pawn",
    "blackpawns": "black_pawn",
    "black_pawn": "black_pawn",
    "black-pawn": "black_pawn",
    "bp": "black_pawn",
    "blackknight": "black_knight",
    "blackknights": "black_knight",
    "black_knight": "black_knight",
    "black-knight": "black_knight",
    "bn": "black_knight",
    "blackbishop": "black_bishop",
    "blackbishops": "black_bishop",
    "black_bishop": "black_bishop",
    "black-bishop": "black_bishop",
    "bb": "black_bishop",
    "blackrook": "black_rook",
    "blackrooks": "black_rook",
    "black_rook": "black_rook",
    "black-rook": "black_rook",
    "br": "black_rook",
    "blackqueen": "black_queen",
    "blackqueens": "black_queen",
    "black_queen": "black_queen",
    "black-queen": "black_queen",
    "bq": "black_queen",
    "blackking": "black_king",
    "blackkings": "black_king",
    "black_king": "black_king",
    "black-king": "black_king",
    "bk": "black_king",
}

PIECE_TYPE_ALIASES = {
    "pawn": "pawn",
    "pawns": "pawn",
    "p": "pawn",
    "knight": "knight",
    "knights": "knight",
    "n": "knight",
    "bishop": "bishop",
    "bishops": "bishop",
    "b": "bishop",
    "rook": "rook",
    "rooks": "rook",
    "r": "rook",
    "queen": "queen",
    "queens": "queen",
    "q": "queen",
    "king": "king",
    "kings": "king",
    "k": "king",
}


def make_dataset_from_labeled_board(
    image_path: Path,
    fen: str,
    out_dir: Path,
    split: str = "train",
    orientation: str = "white",
    debug_dir: Path | None = None,
) -> int:
    image = load_image(image_path)
    board_image = warp_board(image)
    squares = split_squares(board_image)
    fen_board = orient_board(expand_placement(fen), orientation)

    if debug_dir is not None:
        save_debug_board(debug_dir, board_image, squares)

    split_dir = out_dir / split
    counts: dict[str, int] = defaultdict(int)
    written = 0

    for r, row in enumerate(fen_board):
        for c, piece in enumerate(row):
            class_name = class_name_for_piece(piece)
            class_dir = split_dir / class_name
            class_dir.mkdir(parents=True, exist_ok=True)
            counts[class_name] += 1
            output_path = class_dir / f"{image_path.stem}_{r}_{c}_{counts[class_name]:03d}.png"
            cv2.imwrite(str(output_path), squares[r][c])
            written += 1

    return written


def import_class_folder_dataset(
    input_dir: Path,
    out_dir: Path,
    split: str = "train",
    val_ratio: float = 0.0,
    seed: int = 42,
    max_per_class: int | None = None,
    infer_color_from_image: bool = False,
) -> dict[str, int]:
    rng = Random(seed)
    counts: dict[str, int] = defaultdict(int)
    files_by_class = _find_class_folder_images(input_dir, infer_color_from_image=infer_color_from_image)

    for class_name, files in sorted(files_by_class.items()):
        rng.shuffle(files)
        if max_per_class is not None:
            files = files[:max_per_class]
        val_count = int(round(len(files) * val_ratio)) if split == "train" else 0
        val_files = set(files[:val_count])

        for index, path in enumerate(files, start=1):
            target_split = "val" if path in val_files else split
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                counts["skipped_images"] += 1
                continue
            class_dir = out_dir / target_split / class_name
            class_dir.mkdir(parents=True, exist_ok=True)
            output_path = class_dir / f"{path.parent.name}_{path.stem}_{index:07d}.png"
            cv2.imwrite(str(output_path), image)
            counts[class_name] += 1
            counts[f"{target_split}_crops"] += 1

    return dict(counts)


def import_huggingface_image_dataset(
    dataset_name: str,
    out_dir: Path,
    train_split: str = "train",
    val_split: str = "validation",
    max_train: int | None = None,
    max_val: int | None = None,
    progress_every: int = 500,
) -> dict[str, int]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "The 'datasets' package is required. Install it with: "
            "python -m pip install datasets"
        ) from exc

    loaded = load_dataset(dataset_name)
    counts: dict[str, int] = defaultdict(int)
    split_plan = [(train_split, "train", max_train), (val_split, "val", max_val)]
    source = _safe_stem(dataset_name)

    for source_split, target_split, limit in split_plan:
        if source_split not in loaded:
            continue
        dataset = loaded[source_split]
        label_names = _dataset_label_names(dataset)
        max_rows = len(dataset) if limit is None else min(limit, len(dataset))

        for index in range(max_rows):
            row = dataset[index]
            class_name = _class_name_from_dataset_label(row["label"], label_names)
            image = _pil_image_to_bgr(row["image"])
            class_dir = out_dir / target_split / class_name
            class_dir.mkdir(parents=True, exist_ok=True)
            output_path = class_dir / f"{source}_{source_split}_{index:07d}.png"
            cv2.imwrite(str(output_path), image)
            counts[class_name] += 1
            counts[f"{target_split}_crops"] += 1

            if progress_every > 0 and (index + 1) % progress_every == 0:
                print(
                    f"{source_split}: imported {index + 1}/{max_rows} rows",
                    flush=True,
                )

    return dict(counts)


def _find_class_folder_images(input_dir: Path, infer_color_from_image: bool = False) -> dict[str, list[Path]]:
    files_by_class: dict[str, list[Path]] = defaultdict(list)
    for path in input_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        class_name = _class_from_path(path, input_dir, infer_color_from_image=infer_color_from_image)
        if class_name is not None:
            files_by_class[class_name].append(path)

    if not files_by_class:
        raise ValueError(f"No class-labeled images found under {input_dir}")
    return files_by_class


def _class_from_path(path: Path, input_dir: Path, infer_color_from_image: bool = False) -> str | None:
    try:
        relatives = path.relative_to(input_dir).parts[:-1]
    except ValueError:
        relatives = path.parts[:-1]

    for part in reversed(relatives):
        normalized = _normalize_class_alias(part)
        if normalized in CLASS_ALIASES:
            return CLASS_ALIASES[normalized]
        if infer_color_from_image and normalized in PIECE_TYPE_ALIASES:
            color = _infer_piece_color(path)
            return f"{color}_{PIECE_TYPE_ALIASES[normalized]}"
    return None


def _normalize_class_alias(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum() or char in "_-").strip("_-")


def _infer_piece_color(path: Path) -> str:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return "white" if float(image.mean()) >= 128.0 else "black"


def _dataset_label_names(dataset) -> list[str] | None:
    feature = dataset.features.get("label")
    names = getattr(feature, "names", None)
    return list(names) if names is not None else None


def _class_name_from_dataset_label(label, label_names: list[str] | None) -> str:
    if label_names is not None and isinstance(label, int):
        label = label_names[label]
    normalized = _normalize_class_alias(str(label))
    if normalized not in CLASS_ALIASES:
        raise ValueError(f"Unsupported dataset label: {label!r}")
    return CLASS_ALIASES[normalized]


def _pil_image_to_bgr(image) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _safe_stem(value: str) -> str:
    safe = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in safe.split("_") if part)


HF_YOLO_CLASS_NAMES = {
    0: "white_pawn",
    1: "white_knight",
    2: "white_bishop",
    3: "white_rook",
    4: "white_queen",
    5: "white_king",
    6: "black_pawn",
    7: "black_knight",
    8: "black_bishop",
    9: "black_rook",
    10: "black_queen",
    11: "black_king",
}


def make_dataset_from_hf_yolo_zips(
    zip_paths: list[Path],
    out_dir: Path,
    max_train_images: int | None = None,
    max_val_images: int | None = None,
    empty_per_board: int = 8,
    seed: int = 42,
    progress_every: int = 500,
) -> dict[str, int]:
    image_entries, label_entries = _index_hf_yolo_zips(zip_paths)
    rng = Random(seed)
    counts: dict[str, int] = defaultdict(int)
    processed: dict[str, int] = defaultdict(int)
    limits = {"train": max_train_images, "val": max_val_images}

    for key in sorted(image_entries):
        split, stem = key.split("/", 1)
        if split not in ("train", "val"):
            continue
        limit = limits[split]
        if limit is not None and processed[split] >= limit:
            continue
        label_ref = label_entries.get(key)
        if label_ref is None:
            continue

        image = _read_zip_image(*image_entries[key])
        if image is None:
            counts["skipped_images"] += 1
            continue
        labels = _read_zip_text(*label_ref)
        grid = _grid_from_yolo_labels(labels)
        written = _write_grid_crops(
            image=image,
            grid=grid,
            out_dir=out_dir / split,
            stem=stem,
            counts=counts,
            empty_per_board=empty_per_board,
            rng=rng,
        )
        processed[split] += 1
        counts[f"{split}_boards"] += 1
        counts[f"{split}_crops"] += written
        if progress_every > 0 and processed[split] % progress_every == 0:
            print(
                f"{split}: processed {processed[split]} boards, "
                f"wrote {counts[f'{split}_crops']} crops",
                flush=True,
            )

    return dict(counts)


def _index_hf_yolo_zips(zip_paths: list[Path]):
    image_entries: dict[str, tuple[Path, str]] = {}
    label_entries: dict[str, tuple[Path, str]] = {}

    for zip_path in zip_paths:
        with ZipFile(zip_path) as archive:
            for info in archive.infolist():
                parts = Path(info.filename).parts
                if len(parts) != 4 or parts[0] != "chess_yolo_data":
                    continue
                kind, split, filename = parts[1], parts[2], parts[3]
                stem = Path(filename).stem
                key = f"{split}/{stem}"
                if kind == "images" and filename.lower().endswith((".png", ".jpg", ".jpeg")) and info.file_size > 0:
                    image_entries[key] = (zip_path, info.filename)
                elif kind == "labels" and filename.lower().endswith(".txt"):
                    label_entries[key] = (zip_path, info.filename)

    return image_entries, label_entries


def _read_zip_image(zip_path: Path, entry_name: str) -> np.ndarray | None:
    with ZipFile(zip_path) as archive:
        raw = archive.read(entry_name)
    if not raw:
        print(f"skipping empty image: {zip_path.name}:{entry_name}", flush=True)
        return None
    data = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        print(f"skipping undecodable image: {zip_path.name}:{entry_name}", flush=True)
        return None
    return image


def _read_zip_text(zip_path: Path, entry_name: str) -> str:
    with ZipFile(zip_path) as archive:
        return archive.read(entry_name).decode("utf-8")


def _grid_from_yolo_labels(labels: str) -> list[list[str]]:
    grid = [["empty" for _ in range(8)] for _ in range(8)]

    for line in labels.splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        class_id = int(parts[0])
        x_center = float(parts[1])
        y_center = float(parts[2])
        row = min(max(int(y_center * 8), 0), 7)
        col = min(max(int(x_center * 8), 0), 7)
        grid[row][col] = HF_YOLO_CLASS_NAMES[class_id]

    return grid


def _write_grid_crops(
    image: np.ndarray,
    grid: list[list[str]],
    out_dir: Path,
    stem: str,
    counts: dict[str, int],
    empty_per_board: int,
    rng: Random,
) -> int:
    height, width = image.shape[:2]
    square_h = height // 8
    square_w = width // 8
    empty_cells = [(r, c) for r in range(8) for c in range(8) if grid[r][c] == "empty"]
    sampled_empty = set(rng.sample(empty_cells, min(empty_per_board, len(empty_cells))))
    written = 0

    for r in range(8):
        for c in range(8):
            class_name = grid[r][c]
            if class_name == "empty" and (r, c) not in sampled_empty:
                continue
            if class_name not in CLASS_NAMES:
                raise ValueError(f"Unknown class name: {class_name}")
            square = image[r * square_h : (r + 1) * square_h, c * square_w : (c + 1) * square_w]
            class_dir = out_dir / class_name
            class_dir.mkdir(parents=True, exist_ok=True)
            counts[class_name] += 1
            output_path = class_dir / f"{stem}_{r}_{c}_{counts[class_name]:07d}.png"
            cv2.imwrite(str(output_path), square)
            written += 1

    return written
