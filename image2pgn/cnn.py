from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

from .board import background_empty_squares, colored_overlay_review, load_image, save_debug_board, split_squares, warp_board_result
from .board import BoardDetectionResult
from .board_review import load_correction, corrected_board
from .fen import compress_board, orient_board
from .orientation import resolve_orientation
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
    orientation_scores: dict[str, float] | None = None
    orientation_source: str | None = None
    orientation_status: str | None = None
    orientation_details: dict | None = None
    review_squares: tuple[dict, ...] = ()
    board_details: dict | None = None
    board_image: np.ndarray | None = field(default=None, repr=False, compare=False)


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
    board_detector: str = "legacy",
    suppress_empty_background: bool = False,
    low_confidence_policy: str = "empty",
    board_corners: Path | None = None,
    retain_board_image: bool = False,
) -> str:
    return recognize_fen_cnn_result(
        image_path=image_path,
        model_path=model_path,
        orientation=orientation,
        debug_dir=debug_dir,
        device=device,
        threshold=threshold,
        infer_color_from_image=infer_color_from_image,
        board_detector=board_detector,
        suppress_empty_background=suppress_empty_background,
        low_confidence_policy=low_confidence_policy,
        board_corners=board_corners,
        retain_board_image=retain_board_image,
    ).placement


def recognize_fen_cnn_result(
    image_path: Path,
    model_path: Path,
    orientation: str = "white",
    debug_dir: Path | None = None,
    device: str = "auto",
    threshold: float = 0.0,
    infer_color_from_image: bool = False,
    board_detector: str = "legacy",
    suppress_empty_background: bool = False,
    low_confidence_policy: str = "empty",
    board_corners: Path | None = None,
    retain_board_image: bool = False,
) -> RecognitionResult:
    if low_confidence_policy not in ("empty", "review"):
        raise ValueError("low_confidence_policy must be empty or review")
    torch = _require_torch()
    nn = torch.nn
    resolved_device = _resolve_device(torch, device)
    checkpoint = torch.load(model_path, map_location=resolved_device)
    class_names = checkpoint.get("class_names", CLASS_NAMES)

    model = PieceCnn(num_classes=len(class_names), nn=nn).to(resolved_device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    image = load_image(image_path)
    if board_corners is not None:
        corners = load_correction(board_corners, image_path, image)
        detection = BoardDetectionResult(corrected_board(image, corners), {
            "requested_detector": board_detector, "method": "manual", "bounds": None,
            "corners": corners.tolist(), "fallback_reason": None,
            "requires_review": False, "status": "boundary_reviewed",
        })
    else:
        detection = warp_board_result(image, detector=board_detector)
    board_image = detection.image
    if detection.details["requires_review"]:
        print(f"Board requires review: method={detection.details['method']} "
              f"reason={detection.details['fallback_reason'] or 'contour_is_not_board_confirmation'}", flush=True)
    squares = split_squares(board_image)
    overlay_image, overlay_coverage = (colored_overlay_review(board_image) if low_confidence_policy == "review"
                                       else (board_image, [[0.0] * 8 for _ in range(8)]))
    overlay_squares = split_squares(overlay_image)
    overlay_empty = background_empty_squares(overlay_squares) if any(map(any, overlay_coverage)) else [[False] * 8 for _ in range(8)]
    empty_background = background_empty_squares(squares) if suppress_empty_background else [[False] * 8 for _ in range(8)]

    if debug_dir is not None:
        save_debug_board(debug_dir, board_image, squares)
        (debug_dir / "board_detection.json").write_text(
            json.dumps(detection.details, indent=2), encoding="utf-8"
        )

    board: list[list[str]] = []
    review_squares = []
    with torch.no_grad():
        for row_index, row in enumerate(squares):
            fen_row: list[str] = []
            for col_index, square in enumerate(row):
                tensor = _square_to_tensor(square, torch).unsqueeze(0).to(resolved_device)
                logits = model(tensor)
                probabilities = torch.softmax(logits, dim=1)
                score, prediction = torch.max(probabilities, dim=1)
                index = int(prediction.item())
                empty_score = float(probabilities[0, class_names.index("empty")].item())
                class_name = class_name_from_prediction(
                    class_names, index, float(score.item()), threshold, empty_score=empty_score if low_confidence_policy == "review" else None
                )
                hint = None
                if class_names[index] != "empty" and float(score.item()) < threshold:
                    hint = {"reason": "low_confidence"}
                coverage = overlay_coverage[row_index][col_index]
                if coverage:
                    hint = {"reason": "colored_overlay", "overlay_fraction": coverage,
                            "auto_corrected": False}
                    auxiliary = _square_to_tensor(overlay_squares[row_index][col_index], torch).unsqueeze(0).to(resolved_device)
                    clean_probs = torch.softmax(model(auxiliary), dim=1)
                    clean_empty = float(clean_probs[0, class_names.index("empty")].item())
                    hint["clean_empty_score"] = clean_empty
                    # Only remove a phantom piece with independent empty evidence.
                    # Never substitute an inpainted piece type or erase a full highlight.
                    if class_name != "empty" and coverage < 0.5 and clean_empty >= 0.995 and overlay_empty[row_index][col_index]:
                        class_name = "empty"
                        hint["auto_corrected"] = True
                if empty_background[row_index][col_index]:
                    class_name = "empty"
                if infer_color_from_image and class_name != "empty" and not coverage:
                    color_evidence = piece_color_evidence(square)
                    color = color_evidence["color"]
                    if color and color != class_name.split("_", 1)[0]:
                        class_name = f"{color}_{class_name.split('_', 1)[1]}"
                        hint = hint or {"reason": "color_contrast"}
                        hint.update(color_corrected=True, color_evidence=color_evidence)
                if hint is not None:
                    review_squares.append({"screen_row": row_index, "screen_col": col_index,
                                           "class_name": class_names[index],
                                           "score": float(score.item()), "empty_score": empty_score,
                                           "proposed_class_name": class_name, **hint})
                fen_row.append(piece_for_class_name(class_name))
            board.append(fen_row)

    if review_squares:
        print(f"Review {len(review_squares)} uncertain or overlay-covered square(s).", flush=True)

    if orientation == "auto":
        white_placement = compress_board(orient_board(board, "white"))
        black_placement = compress_board(orient_board(board, "black"))
        details = resolve_orientation(white_placement, black_placement, board_image)
        chosen, scores = details["orientation"], details["scores"]
        print(f"orientation={chosen} source={details['source']} status={details['status']} "
              f"white_score={scores['white']:.2f} black_score={scores['black']:.2f}", flush=True)
        if details["source"] == "position":
            print("Orientation is an estimate; override with --orientation white or black.", flush=True)
        return RecognitionResult(
            placement=black_placement if chosen == "black" else white_placement,
            orientation=chosen,
            orientation_scores=scores,
            orientation_source=details["source"],
            orientation_status=details["status"],
            orientation_details=details,
            review_squares=tuple(review_squares),
            board_details=detection.details,
            board_image=board_image if retain_board_image else None,
        )

    board = orient_board(board, orientation)
    return RecognitionResult(placement=compress_board(board), orientation=orientation, review_squares=tuple(review_squares), board_details=detection.details, board_image=board_image if retain_board_image else None)


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


def class_name_from_prediction(class_names: list[str], index: int, score: float,
                               threshold: float, empty_score: float | None = None) -> str:
    # With full probabilities, distinguish occupancy from piece-type uncertainty.
    # Calls without empty_score preserve the historical helper contract.
    confidence = score if empty_score is None else 1.0 - empty_score
    if confidence < threshold:
        return "empty"
    return class_names[index]


def class_name_with_inferred_color(square: np.ndarray, class_name: str) -> str:
    if class_name == "empty":
        return class_name
    piece_type = class_name.split("_", 1)[1]
    color = infer_piece_color_from_square(square)
    return f"{color}_{piece_type}" if color else class_name


def piece_color_evidence(square: np.ndarray) -> dict:
    """Compare a piece's interior with its own square, abstaining on weak cues.

    Relative contrast alone reverses black pieces on very dark tiles. Interior
    luminance and low saturation must support the same interpretation. Thin
    dark outlines, coordinate labels and corner badges are not the piece body.
    """
    tile = cv2.resize(square, (80, 80), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(tile, cv2.COLOR_BGR2LAB).astype(np.float32)
    corners = np.concatenate([lab[y:y + 8, x:x + 8].reshape(-1, 3)
                              for y in (4, 68) for x in (4, 68)])
    background = np.median(corners, axis=0)
    tolerance = np.maximum(np.median(np.abs(corners - background), axis=0) * 4, [16, 10, 10])
    foreground = (np.max(np.abs(lab - background) / tolerance, axis=2) > 1).astype(np.uint8)
    foreground[:9] = foreground[71:] = 0
    foreground[:, :9] = foreground[:, 71:] = 0
    count, labels, stats, centers = cv2.connectedComponentsWithStats(foreground, 8)
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 100
                  and 22 <= centers[i][0] <= 58 and 18 <= centers[i][1] <= 62]
    if not candidates:
        return {"color": None, "reason": "no_central_body"}
    selected = max(candidates, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    region = (labels == selected).astype(np.uint8)
    interior = cv2.erode(region, np.ones((5, 5), np.uint8)) > 0
    if interior.sum() < 50 or region.mean() > 0.55:
        return {"color": None, "reason": "ambiguous_body_area"}
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY).astype(np.float32)
    body_brightness = float(np.median(gray[interior]))
    background_brightness = float(np.median(np.concatenate(
        [gray[y:y + 8, x:x + 8].reshape(-1) for y in (4, 68) for x in (4, 68)])))
    contrast = body_brightness - background_brightness
    saturation = float(np.median(cv2.cvtColor(tile, cv2.COLOR_BGR2HSV)[:, :, 1][interior]))
    color = None
    if saturation <= 60:
        if body_brightness <= 120 and contrast <= -18:
            color = "black"
        elif body_brightness >= 180 and contrast >= 18:
            color = "white"
    return {"color": color, "reason": "body_background_contrast" if color else "ambiguous_contrast",
            "body_brightness": body_brightness, "background_brightness": background_brightness,
            "contrast": contrast, "body_saturation": saturation, "body_pixels": int(interior.sum())}


def infer_piece_color_from_square(square: np.ndarray) -> str | None:
    return piece_color_evidence(square)["color"]


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
