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


def warp_board(image: np.ndarray, output_size: int = BOARD_SIZE) -> np.ndarray:
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

