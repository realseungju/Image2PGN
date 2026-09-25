from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from image2pgn import webapp
from image2pgn.analyze import PositionAnalysis


def configured_app(tmp_path: Path):
    model = tmp_path / "model.pt"
    model.write_bytes(b"fixture")
    return webapp.create_app(model_path=model, engine_path=tmp_path / "stockfish")


def test_index_serves_english_analysis_workspace(tmp_path):
    response = TestClient(configured_app(tmp_path)).get("/")
    assert response.status_code == 200
    assert "Drop a chess screenshot" in response.text
    assert "Analyze with Stockfish" in response.text
    assert 'id="new-analysis-button"' in response.text
    assert 'id="image-input" type="file" accept="image/png,image/jpeg" multiple' in response.text


def test_recognize_rejects_non_image(tmp_path):
    response = TestClient(configured_app(tmp_path)).post(
        "/api/recognize", files={"image": ("x.txt", b"no", "text/plain")}
    )
    assert response.status_code == 415


def test_recognize_rejects_oversized_image(tmp_path):
    response = TestClient(configured_app(tmp_path)).post(
        "/api/recognize",
        files={
            "image": (
                "large.png",
                b"x" * (webapp.MAX_UPLOAD_BYTES + 1),
                "image/png",
            )
        },
    )
    assert response.status_code == 413


def test_recognize_returns_board_and_deletes_temporary_file(tmp_path, monkeypatch):
    captured = {}
    def fake_recognize(**kwargs):
        captured["path"] = kwargs["image_path"]
        assert captured["path"].exists()
        return SimpleNamespace(
            placement="8/8/8/8/8/8/8/4K2k", orientation="white",
            orientation_status="estimated", orientation_source="position",
            orientation_details={"reason": "fixture"}, review_squares=(),
            board_details={"method": "grid-v2", "requires_review": False},
            board_image=np.zeros((640, 640, 3), dtype=np.uint8),
        )
    monkeypatch.setattr(webapp, "recognize_fen_cnn_result", fake_recognize)
    response = TestClient(configured_app(tmp_path)).post(
        "/api/recognize", files={"image": ("board.png", b"fake-png", "image/png")}
    )
    assert response.status_code == 200
    assert response.json()["placement"].endswith("4K2k")
    assert response.json()["board_image"].startswith("data:image/png;base64,")
    assert not captured["path"].exists()


def test_analyze_requires_game_history_confirmation(tmp_path):
    response = TestClient(configured_app(tmp_path)).post(
        "/api/analyze", json={"fen": "8/8/8/8/8/8/8/4K2k w - - 0 1"}
    )
    assert response.status_code == 400
    assert "Confirm" in response.json()["detail"]


def test_analyze_returns_structured_result(tmp_path, monkeypatch):
    result = PositionAnalysis(
        fen="8/8/8/8/8/8/8/4K2k w - - 0 1", legal=True, turn="white",
        side_to_move="White", evaluation="+0.10", evaluation_cp=10, mate=None,
        summary="fixture", moves=[], threats=[], warnings=[],
    )
    monkeypatch.setattr(webapp, "analyze_fen", lambda **kwargs: result)
    response = TestClient(configured_app(tmp_path)).post(
        "/api/analyze", json={
            "fen": result.fen, "confirmed_history": True, "movetime_ms": 100, "top": 3,
        }
    )
    assert response.status_code == 200
    assert response.json()["evaluation"] == "+0.10"


def test_analyze_reports_invalid_fen(tmp_path, monkeypatch):
    def reject_fen(**kwargs):
        raise ValueError("invalid FEN")

    monkeypatch.setattr(webapp, "analyze_fen", reject_fen)
    response = TestClient(configured_app(tmp_path)).post(
        "/api/analyze",
        json={
            "fen": "not a valid FEN",
            "confirmed_history": True,
        },
    )
    assert response.status_code == 400
    assert "FEN" in response.json()["detail"]
