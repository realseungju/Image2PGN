"""One local entry point: uv run chesslens [--engine PATH] [--doctor]."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import webbrowser

ASSETS = Path(__file__).with_name("assets")
BUNDLED_MODEL = ASSETS / "piece_classifier.pt"


def default_model() -> Path:
    configured = os.environ.get("CHESSLENS_MODEL_PATH")
    return Path(configured).expanduser() if configured else BUNDLED_MODEL


def check_model(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"Model not found: {path}. Use --model PATH or restore the bundled image2pgn/assets model.")
    if path.resolve() == BUNDLED_MODEL.resolve():
        manifest = json.loads((ASSETS / "model.json").read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Bundled model checksum mismatch. Restore it from the repository before running.")


def configuration(model: Path | None, engine: Path | None) -> tuple[Path, Path]:
    from .analyze import resolve_engine_path
    selected = (model or default_model()).expanduser().resolve()
    check_model(selected)
    configured = engine or (Path(os.environ["CHESSLENS_ENGINE_PATH"]) if os.environ.get("CHESSLENS_ENGINE_PATH") else None)
    try:
        resolved = resolve_engine_path(configured.expanduser() if configured else None)
    except FileNotFoundError as exc:
        raise ValueError("Stockfish not found. Install it from https://stockfishchess.org/download/ and use --engine PATH, CHESSLENS_ENGINE_PATH, or PATH.") from exc
    if not resolved.is_file():
        raise ValueError(f"Stockfish must be an executable file: {resolved}")
    return selected, resolved.resolve()


def probe_engine(path: Path) -> str:
    import chess.engine
    try:
        with chess.engine.SimpleEngine.popen_uci(str(path), timeout=10) as engine:
            return engine.id.get("name", "UCI engine")
    except chess.engine.EngineError as exc:
        raise ValueError("Could not start the UCI engine. Check the Stockfish executable and CPU compatibility.") from exc


def open_when_ready(server, url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not server.should_exit:
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(.1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Start the local ChessLens image-upload and analysis app.")
    parser.add_argument("--port", type=int, default=8771, help="Loopback HTTP port (default: 8771).")
    parser.add_argument("--model", type=Path, help="Use a custom PieceCNN checkpoint.")
    parser.add_argument("--engine", type=Path, help="Path to a separately installed Stockfish executable.")
    parser.add_argument("--device", default="cpu", help="PyTorch device (default: cpu).")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser.")
    parser.add_argument("--doctor", action="store_true", help="Check the model and UCI engine, then exit.")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    try:
        model, engine = configuration(args.model, args.engine)
        engine_name = probe_engine(engine)
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        parser.error(str(exc))
    print(f"Model ready: {model.name}")
    print(f"Engine ready: {engine_name}")
    if args.doctor:
        print("ChessLens is ready. Run `uv run chesslens` to open the web app.")
        return
    import uvicorn
    from .webapp import create_app
    os.environ["CHESSLENS_PORT"] = str(args.port)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"ChessLens: {url}\nUpload PNG/JPEG, review the board and game state, then analyze. Ctrl+C stops the server.", flush=True)
    server = uvicorn.Server(uvicorn.Config(create_app(model, engine, args.device), host="127.0.0.1", port=args.port, log_level="warning"))
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(server, url), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
