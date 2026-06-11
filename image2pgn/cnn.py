from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

from .board import load_image, save_debug_board, split_squares, warp_board
from .fen import choose_orientation_by_score, compress_board, orient_board
from .pieces import CLASS_NAMES, piece_for_class_name


IMAGE_SIZE = 96


@dataclass(frozen=True)
class TrainConfig:
    data_dir: Path
    model_path: Path
    extra_data_dirs: tuple[Path, ...] = ()
    epochs: int = 12
    batch_size: int = 32
    learning_rate: float = 0.001
    device: str = "auto"
    progress_every: int = 100


@dataclass(frozen=True)
class RecognitionResult:
    placement: str
    orientation: str
    orientation_scores: dict[str, int] | None = None


def train_cnn(config: TrainConfig) -> None:
    torch = _require_torch()
    nn = torch.nn
    optim = torch.optim
    DataLoader = torch.utils.data.DataLoader

    device = _resolve_device(torch, config.device)
    train_dataset = MultiRootSquareImageDataset(
        [config.data_dir, *config.extra_data_dirs],
        split="train",
        torch=torch,
        augment=True,
    )
    val_dir = config.data_dir / "val"
    val_roots = [root for root in [config.data_dir, *config.extra_data_dirs] if (root / "val").exists()]
    val_dataset = (
        MultiRootSquareImageDataset(val_roots, split="val", torch=torch, augment=False)
        if val_roots
        else None
    )

    if len(train_dataset) == 0:
        roots = ", ".join(str(root / "train") for root in [config.data_dir, *config.extra_data_dirs])
        raise ValueError(f"No training images found under: {roots}")

    model = PieceCnn(num_classes=len(CLASS_NAMES), nn=nn).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=config.batch_size) if val_dataset else None

    for epoch in range(1, config.epochs + 1):
        train_loss, train_acc = _run_epoch(
            torch,
            model,
            train_loader,
            criterion,
            optimizer,
            device,
            epoch=epoch,
            progress_every=config.progress_every,
        )
        line = f"epoch {epoch:03d} train_loss={train_loss:.4f} train_acc={train_acc:.3f}"
        if val_loader is not None:
            val_loss, val_acc = _run_epoch(
                torch,
                model,
                val_loader,
                criterion,
                None,
                device,
                epoch=epoch,
                progress_every=0,
            )
            line += f" val_loss={val_loss:.4f} val_acc={val_acc:.3f}"
        print(line)

    config.model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": model.state_dict(),
            "class_names": CLASS_NAMES,
            "image_size": IMAGE_SIZE,
        },
        config.model_path,
    )
    metadata_path = config.model_path.with_suffix(config.model_path.suffix + ".json")
    metadata_path.write_text(
        json.dumps({"class_names": CLASS_NAMES, "image_size": IMAGE_SIZE}, indent=2),
        encoding="utf-8",
    )


def recognize_fen_cnn(
    image_path: Path,
    model_path: Path,
    orientation: str = "white",
    debug_dir: Path | None = None,
    device: str = "auto",
    threshold: float = 0.0,
    infer_color_from_image: bool = False,
) -> str:
    return recognize_fen_cnn_result(
        image_path=image_path,
        model_path=model_path,
        orientation=orientation,
        debug_dir=debug_dir,
        device=device,
        threshold=threshold,
        infer_color_from_image=infer_color_from_image,
    ).placement


def recognize_fen_cnn_result(
    image_path: Path,
    model_path: Path,
    orientation: str = "white",
    debug_dir: Path | None = None,
    device: str = "auto",
    threshold: float = 0.0,
    infer_color_from_image: bool = False,
) -> RecognitionResult:
    torch = _require_torch()
    nn = torch.nn
    resolved_device = _resolve_device(torch, device)
    checkpoint = torch.load(model_path, map_location=resolved_device)
    class_names = checkpoint.get("class_names", CLASS_NAMES)

    model = PieceCnn(num_classes=len(class_names), nn=nn).to(resolved_device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    image = load_image(image_path)
    board_image = warp_board(image)
    squares = split_squares(board_image)

    if debug_dir is not None:
        save_debug_board(debug_dir, board_image, squares)

    board: list[list[str]] = []
    with torch.no_grad():
        for row in squares:
            fen_row: list[str] = []
            for square in row:
                tensor = _square_to_tensor(square, torch).unsqueeze(0).to(resolved_device)
                logits = model(tensor)
                probabilities = torch.softmax(logits, dim=1)
                score, prediction = torch.max(probabilities, dim=1)
                index = int(prediction.item())
                class_name = class_name_from_prediction(class_names, index, float(score.item()), threshold)
                if infer_color_from_image and class_name != "empty":
                    class_name = class_name_with_inferred_color(square, class_name)
                fen_row.append(piece_for_class_name(class_name))
            board.append(fen_row)

    if orientation == "auto":
        white_placement = compress_board(orient_board(board, "white"))
        black_placement = compress_board(orient_board(board, "black"))
        chosen, scores = choose_orientation_by_score(white_placement, black_placement)
        print(f"orientation={chosen} white_score={scores['white']} black_score={scores['black']}", flush=True)
        return RecognitionResult(
            placement=black_placement if chosen == "black" else white_placement,
            orientation=chosen,
            orientation_scores=scores,
        )

    board = orient_board(board, orientation)
    return RecognitionResult(placement=compress_board(board), orientation=orientation)


def evaluate_cnn(
    data_dir: Path,
    model_path: Path,
    extra_data_dirs: tuple[Path, ...] = (),
    split: str = "val",
    device: str = "auto",
    batch_size: int = 128,
) -> dict:
    torch = _require_torch()
    nn = torch.nn
    DataLoader = torch.utils.data.DataLoader
    resolved_device = _resolve_device(torch, device)
    checkpoint = torch.load(model_path, map_location=resolved_device)
    class_names = checkpoint.get("class_names", CLASS_NAMES)

    dataset = MultiRootSquareImageDataset(
        [data_dir, *extra_data_dirs],
        split=split,
        torch=torch,
        augment=False,
    )
    if len(dataset) == 0:
        roots = ", ".join(str(root / split) for root in [data_dir, *extra_data_dirs])
        raise ValueError(f"No evaluation images found under: {roots}")

    model = PieceCnn(num_classes=len(class_names), nn=nn).to(resolved_device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    loader = DataLoader(dataset, batch_size=batch_size)
    confusion = torch.zeros((len(class_names), len(class_names)), dtype=torch.int64)
    total = 0
    correct = 0

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(resolved_device)
            labels = labels.to(resolved_device)
            logits = model(images)
            predictions = torch.argmax(logits, dim=1)
            correct += int((predictions == labels).sum().item())
            total += int(labels.numel())
            for truth, prediction in zip(labels.cpu(), predictions.cpu()):
                confusion[int(truth), int(prediction)] += 1

    per_class = {}
    for index, class_name in enumerate(class_names):
        support = int(confusion[index].sum().item())
        class_correct = int(confusion[index, index].item())
        per_class[class_name] = {
            "support": support,
            "correct": class_correct,
            "accuracy": class_correct / support if support else 0.0,
        }

    mistakes = []
    for truth_index, truth_name in enumerate(class_names):
        for pred_index, pred_name in enumerate(class_names):
            if truth_index == pred_index:
                continue
            count = int(confusion[truth_index, pred_index].item())
            if count:
                mistakes.append((count, truth_name, pred_name))
    mistakes.sort(reverse=True)

    return {
        "split": split,
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "per_class": per_class,
        "mistakes": mistakes,
    }


class SquareImageDataset:
    def __init__(self, root: Path, torch, augment: bool = False):
        self.root = root
        self.torch = torch
        self.augment = augment
        self.samples: list[tuple[Path, int]] = []

        if not root.exists():
            return

        for index, class_name in enumerate(CLASS_NAMES):
            class_dir = root / class_name
            if not class_dir.exists():
                continue
            for path in sorted(class_dir.glob("*.png")) + sorted(class_dir.glob("*.jpg")) + sorted(class_dir.glob("*.jpeg")):
                self.samples.append((path, index))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, label = self.samples[index]
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Could not read image: {path}")
        if self.augment:
            image = _augment_square(image)
        return _square_to_tensor(image, self.torch), self.torch.tensor(label, dtype=self.torch.long)


class MultiRootSquareImageDataset:
    def __init__(self, roots: list[Path], split: str, torch, augment: bool = False):
        self.datasets = [
            SquareImageDataset(root / split, torch=torch, augment=augment)
            for root in roots
        ]
        self.datasets = [dataset for dataset in self.datasets if len(dataset) > 0]
        self.offsets: list[tuple[int, SquareImageDataset]] = []
        total = 0
        for dataset in self.datasets:
            total += len(dataset)
            self.offsets.append((total, dataset))

    def __len__(self) -> int:
        return self.offsets[-1][0] if self.offsets else 0

    def __getitem__(self, index: int):
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        previous = 0
        for end, dataset in self.offsets:
            if index < end:
                return dataset[index - previous]
            previous = end
        raise IndexError(index)


class PieceCnn:
    def __new__(cls, num_classes: int, nn):
        return nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 192, kernel_size=3, padding=1),
            nn.BatchNorm2d(192),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Dropout(0.25),
            nn.Linear(192, num_classes),
        )


def class_name_from_prediction(class_names: list[str], index: int, score: float, threshold: float) -> str:
    if score < threshold:
        return "empty"
    return class_names[index]


def class_name_with_inferred_color(square: np.ndarray, class_name: str) -> str:
    if class_name == "empty":
        return class_name
    piece_type = class_name.split("_", 1)[1]
    color = infer_piece_color_from_square(square)
    return f"{color}_{piece_type}"


def infer_piece_color_from_square(square: np.ndarray) -> str:
    gray = cv2.cvtColor(square, cv2.COLOR_BGR2GRAY)
    threshold_value = _otsu_threshold(gray)
    dark_pixels = gray[gray <= threshold_value]
    light_pixels = gray[gray > threshold_value]
    if len(dark_pixels) == 0 or len(light_pixels) == 0:
        return "white" if float(gray.mean()) >= 128.0 else "black"

    dark_mean = float(dark_pixels.mean())
    light_mean = float(light_pixels.mean())
    global_mean = float(gray.mean())

    # Piece pixels are usually the smaller foreground cluster. If the foreground
    # is ambiguous, use the whole square brightness as a stable fallback.
    dark_ratio = len(dark_pixels) / gray.size
    light_ratio = len(light_pixels) / gray.size
    foreground_mean = dark_mean if dark_ratio < light_ratio else light_mean
    if abs(foreground_mean - global_mean) < 18:
        foreground_mean = global_mean

    return "white" if foreground_mean >= 128.0 else "black"


def _otsu_threshold(gray: np.ndarray) -> float:
    threshold_value, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(threshold_value)


def _run_epoch(torch, model, loader, criterion, optimizer, device, epoch: int, progress_every: int):
    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    correct = 0
    total = 0

    total_batches = len(loader)
    for batch_index, (images, labels) in enumerate(loader, start=1):
        images = images.to(device)
        labels = labels.to(device)
        if training:
            optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        if training:
            loss.backward()
            optimizer.step()

        batch_size = labels.size(0)
        total_loss += float(loss.item()) * batch_size
        correct += int((torch.argmax(logits, dim=1) == labels).sum().item())
        total += batch_size
        if training and progress_every > 0 and batch_index % progress_every == 0:
            print(
                f"epoch {epoch:03d} batch {batch_index}/{total_batches} "
                f"loss={total_loss / max(total, 1):.4f} acc={correct / max(total, 1):.3f}",
                flush=True,
            )

    return total_loss / max(total, 1), correct / max(total, 1)


def _square_to_tensor(square: np.ndarray, torch):
    image = cv2.resize(square, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    image = np.transpose(image, (2, 0, 1))
    return torch.from_numpy(image)


def _augment_square(image: np.ndarray) -> np.ndarray:
    if np.random.rand() < 0.5:
        alpha = float(np.random.uniform(0.85, 1.15))
        beta = float(np.random.uniform(-18, 18))
        image = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    if np.random.rand() < 0.35:
        image = cv2.GaussianBlur(image, (3, 3), 0)
    return image


def _resolve_device(torch, device: str):
    if device != "auto":
        return torch.device(device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for CNN training/inference. Install it with: "
            "python -m pip install torch"
        ) from exc
    return torch
