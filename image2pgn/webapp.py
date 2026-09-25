from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import tempfile

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .analyze import analyze_fen
from .cnn import recognize_fen_cnn_result


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
WEB_DIR = Path(__file__).with_name("web")


@dataclass(frozen=True)
class WebConfig:
    model_path: Path | None
    engine_path: Path | None
    device: str = "cpu"


class AnalyzeRequest(BaseModel):
    fen: str = Field(min_length=5, max_length=120)
    confirmed_history: bool = False
    depth: int = Field(default=14, ge=1, le=30)
    movetime_ms: int | None = Field(default=None, ge=50, le=5000)
    top: int = Field(default=3, ge=1, le=5)


def create_app(model_path: Path | None = None, engine_path: Path | None = None, device: str = "cpu") -> FastAPI:
    app = FastAPI(title="ChessLens", docs_url="/api/docs", redoc_url=None)
    app.state.config = WebConfig(
        model_path=model_path or _path_from_env("CHESSLENS_MODEL_PATH"),
        engine_path=engine_path or _path_from_env("CHESSLENS_ENGINE_PATH"),
        device=device,
    )
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.post("/api/recognize")
    async def recognize(image: UploadFile = File(...)):
        config: WebConfig = app.state.config
        if config.model_path is None:
            raise HTTPException(503, "The PieceCNN model path is not configured.")
        if not config.model_path.is_file():
            raise HTTPException(503, "The configured PieceCNN model file does not exist.")
        suffix = ALLOWED_CONTENT_TYPES.get((image.content_type or "").lower())
        if suffix is None:
            raise HTTPException(415, "Only PNG and JPEG images are supported.")
        payload = await image.read(MAX_UPLOAD_BYTES + 1)
        if not payload:
            raise HTTPException(400, "The uploaded image is empty.")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Images must be 10 MiB or smaller.")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="chesslens-", suffix=suffix, delete=False) as temporary:
                temporary.write(payload)
                temporary_path = Path(temporary.name)
            result = await run_in_threadpool(
                recognize_fen_cnn_result,
                image_path=temporary_path,
                model_path=config.model_path,
                orientation="auto",
                device=config.device,
                threshold=0.5,
                board_detector="grid-v2",
                suppress_empty_background=False,
                low_confidence_policy="review",
                retain_board_image=True,
            )
            return {
                "placement": result.placement,
                "orientation": result.orientation,
                "orientation_status": result.orientation_status,
                "orientation_source": result.orientation_source,
                "orientation_details": result.orientation_details,
                "board_details": result.board_details,
                "review_squares": list(result.review_squares),
                "board_image": _png_data_url(result.board_image),
            }
        except HTTPException:
            raise
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, f"The board could not be recognized: {exc}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.post("/api/analyze")
    async def analyze(request: AnalyzeRequest):
        if not request.confirmed_history:
            raise HTTPException(400, "Confirm the side to move and game-state fields before analysis.")
        config: WebConfig = app.state.config
        try:
            result = await run_in_threadpool(
                analyze_fen,
                fen=request.fen,
                engine_path=config.engine_path,
                depth=request.depth,
                top=request.top,
                movetime_ms=request.movetime_ms,
            )
            return asdict(result)
        except ValueError as exc:
            raise HTTPException(400, f"Check the FEN: {exc}") from exc
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, f"Stockfish analysis failed: {exc}") from exc

    return app


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _png_data_url(image) -> str:
    if image is None:
        raise ValueError("Recognition did not retain the normalized board image.")
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Could not encode normalized board image.")
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


app = create_app()
