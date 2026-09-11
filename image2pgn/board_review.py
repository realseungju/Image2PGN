"""Local board-boundary review artifacts and validated correction files."""
from pathlib import Path
import base64
import hashlib
import json

import cv2
import numpy as np

from .board import load_image, warp_board_result


def validate_corners(points, width, height):
    try:
        quad = np.asarray(points, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("Corners must be four numeric x/y pairs") from exc
    if quad.shape != (4, 2) or not np.isfinite(quad).all():
        raise ValueError("Corners must be four finite x/y pairs")
    if (quad < 0).any() or (quad[:, 0] > width - 1).any() or (quad[:, 1] > height - 1).any():
        raise ValueError("Corners must be inside the source image")
    edges = np.roll(quad, -1, axis=0) - quad
    cross = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
    if not (cross > 0).all() or cv2.contourArea(quad.astype(np.float32)) < 64:
        raise ValueError("Use a convex, nondegenerate TL, TR, BR, BL quadrilateral")
    # Prevent a cyclically shifted polygon from silently rotating the board.
    if (quad[0, 0] + quad[3, 0] >= quad[1, 0] + quad[2, 0]
            or quad[0, 1] + quad[1, 1] >= quad[2, 1] + quad[3, 1]):
        raise ValueError("Corner order must be screen TL, TR, BR, BL")
    return quad.astype(np.float32)


def image_identity(image_path, image):
    return {"sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "width": image.shape[1], "height": image.shape[0]}


def load_correction(path, image_path, image):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or document.get("schema") != "chess-board-corners-v1":
        raise ValueError("Unsupported board correction schema")
    if document.get("reviewed") is not True or document.get("incomplete") is not False:
        raise ValueError("Confirm complete board boundaries before using this correction")
    if document.get("image") != image_identity(image_path, image):
        raise ValueError("Correction belongs to a different image or image size")
    return validate_corners(document.get("corners"), image.shape[1], image.shape[0])


def corrected_board(image, corners, output_size=640):
    points = validate_corners(corners, image.shape[1], image.shape[0])
    target = np.array([[0, 0], [output_size-1, 0], [output_size-1, output_size-1],
                       [0, output_size-1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, transform, (output_size, output_size))


def build_review(image_path, output_path):
    image = load_image(image_path)
    detection = warp_board_result(image, detector="grid")
    details = detection.details
    if details["corners"] is not None:
        corners = details["corners"]
    else:
        x, y, width, height = details["bounds"]
        corners = [[x, y], [x+width-1, y], [x+width-1, y+height-1], [x, y+height-1]]
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Could not embed source image")
    payload = {"filename": image_path.name, "image": image_identity(image_path, image),
               "corners": corners, "detection": details,
               "dataUrl": "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")}
    package = Path(__file__).parent
    html = (package / "board_review.html").read_text(encoding="utf-8")
    math = (package / "board_geometry.js").read_text(encoding="utf-8")
    html = html.replace("/*GEOMETRY*/", math).replace("/*PAYLOAD*/", json.dumps(payload).replace("<", "\\u003c"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return details
