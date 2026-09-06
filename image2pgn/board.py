from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


BOARD_SIZE = 640
SQUARE_SIZE = BOARD_SIZE // 8


def load_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


def warp_board(image: np.ndarray, output_size: int = BOARD_SIZE, *, detector: str = "legacy") -> np.ndarray:
    if detector not in {"grid", "legacy"}:
        raise ValueError("detector must be 'grid' or 'legacy'.")
    if detector == "grid":
        bounds = find_screenshot_board(image)
        if bounds is not None:
            x, y, width, height = bounds
            return cv2.resize(image[y:y + height, x:x + width], (output_size, output_size), interpolation=cv2.INTER_AREA)
    contour = _find_board_contour(image)
    if contour is None:
        return _center_square_crop(image, output_size)

    points = _order_points(contour.reshape(4, 2).astype("float32"))
    target = np.array(
        [
            [0, 0],
            [output_size - 1, 0],
            [output_size - 1, output_size - 1],
            [0, output_size - 1],
        ],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, matrix, (output_size, output_size))


def _checker_template(width: int, height: int) -> np.ndarray:
    rows, cols = np.indices((height, width))
    return (((cols * 8 // width + rows * 8 // height) % 2) * 2 - 1).astype(np.float32)


def _best_checker_match(gray: np.ndarray, width: int, height: int):
    scores = cv2.matchTemplate(gray, _checker_template(width, height), cv2.TM_CCOEFF_NORMED)
    low, high, low_at, high_at = cv2.minMaxLoc(scores)
    return (-low, low_at) if -low > high else (high, high_at)


def find_screenshot_board(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Find an axis-aligned 8x8 background pattern, not the biggest UI rectangle.

    Coarse normalized correlation is refined near its best location. Both board
    polarities are accepted. Low evidence retains the perspective-contour path.
    Small boards (< half screenshot width), severe perspective and occlusion
    remain outside this screenshot-specific detector's search range.
    """
    source_h, source_w = image.shape[:2]
    if min(source_h, source_w) < 32:
        return None
    scale = 160 / source_w
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (160, max(1, round(source_h * scale))), interpolation=cv2.INTER_AREA).astype(np.float32)
    best_score, best = -1.0, None
    for width in range(80, 161, 2):
        for aspect in (0.92, 1.0, 1.04):
            height = round(width * aspect)
            if height > small.shape[0]:
                continue
            score, (x, y) = _best_checker_match(small, width, height)
            if score > best_score:
                best_score, best = score, (x, y, width, height)
    if best is None or best_score < 0.35:
        return None

    # Refine against a larger image, without a full-resolution global search.
    fine_scale = min(1.0, 640 / source_w)
    fine = cv2.resize(gray, (round(source_w * fine_scale), round(source_h * fine_scale)), interpolation=cv2.INTER_AREA).astype(np.float32)
    factor = fine_scale / scale
    x, y, width, height = [round(v * factor) for v in best]
    radius = max(3, round(2 * factor))
    left, top = max(0, x - radius), max(0, y - radius)
    right = min(fine.shape[1], x + width + radius)
    bottom = min(fine.shape[0], y + height + radius)
    roi = fine[top:bottom, left:right]
    refined_score, refined = -1.0, (x, y, width, height)
    for w in range(max(16, width - radius), min(roi.shape[1], width + radius) + 1, 2):
        for h in range(max(16, height - radius), min(roi.shape[0], height + radius) + 1, 2):
            score, (dx, dy) = _best_checker_match(roi, w, h)
            if score > refined_score:
                refined_score, refined = score, (left + dx, top + dy, w, h)
    x, y, width, height = [round(v / fine_scale) for v in refined]
    return x, y, min(width, source_w - x), min(height, source_h - y)


def background_empty_squares(squares: list[list[np.ndarray]]) -> list[list[bool]]:
    """Conservative empty evidence from local corner color and board texture.

    A square is empty only if no substantial central component differs from its
    background. Shared corner residuals accommodate textured themes. This is a
    board-context postprocessor, not retraining or an estimate of piece type.
    """
    labs, backgrounds, residuals = [], [], []
    for row in squares:
        for square in row:
            square = cv2.resize(square, (80, 80), interpolation=cv2.INTER_AREA)
            lab = cv2.cvtColor(square, cv2.COLOR_BGR2LAB).astype(np.float32)
            corners = np.concatenate([lab[y:y + 10, x:x + 10].reshape(-1, 3) for y in (5, 65) for x in (5, 65)])
            color = np.median(corners, axis=0)
            labs.append(lab)
            backgrounds.append(color)
            residuals.append(corners - color)
    tolerance = np.maximum(np.quantile(np.abs(np.concatenate(residuals)), 0.90, axis=0) * 1.5, [16, 8, 8])
    empty = []
    for lab, color in zip(labs, backgrounds):
        foreground = (np.max(np.abs(lab - color) / tolerance, axis=2) > 1).astype(np.uint8)
        foreground[:12] = foreground[68:] = 0
        foreground[:, :12] = foreground[:, 68:] = 0
        _, _, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
        largest = max(stats[1:, cv2.CC_STAT_AREA], default=0)
        empty.append(bool(largest / (56 * 56) < 0.035))
    return [empty[r * 8:(r + 1) * 8] for r in range(8)]


def split_squares(board_image: np.ndarray) -> list[list[np.ndarray]]:
    height, width = board_image.shape[:2]
    square_h = height // 8
    square_w = width // 8
    return [
        [
            board_image[r * square_h : (r + 1) * square_h, c * square_w : (c + 1) * square_w]
            for c in range(8)
        ]
        for r in range(8)
    ]


def save_debug_board(debug_dir: Path, board_image: np.ndarray, squares: list[list[np.ndarray]]) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "warped_board.png"), board_image)
    squares_dir = debug_dir / "squares"
    squares_dir.mkdir(exist_ok=True)
    for r, row in enumerate(squares):
        for c, square in enumerate(row):
            cv2.imwrite(str(squares_dir / f"{r}_{c}.png"), square)


def _center_square_crop(image: np.ndarray, output_size: int) -> np.ndarray:
    height, width = image.shape[:2]
    side = min(height, width)
    y0 = (height - side) // 2
    x0 = (width - side) // 2
    crop = image[y0 : y0 + side, x0 : x0 + side]
    return cv2.resize(crop, (output_size, output_size), interpolation=cv2.INTER_AREA)


def _find_board_contour(image: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.shape[0] * image.shape[1]

    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.08:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, y, w, h = cv2.boundingRect(approx)
        aspect = w / max(h, 1)
        if 0.75 <= aspect <= 1.33:
            candidates.append((area, approx))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1)

    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]
    return ordered
