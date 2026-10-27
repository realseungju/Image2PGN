from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from image2pgn import launcher, webapp


def test_bundled_model_is_distributed_and_verified(monkeypatch):
    monkeypatch.delenv("CHESSLENS_MODEL_PATH", raising=False)
    assert launcher.default_model() == launcher.BUNDLED_MODEL
    launcher.check_model(launcher.default_model())


def test_custom_paths_and_environment_precedence(tmp_path, monkeypatch):
    model = tmp_path / "custom.pt"
    engine = tmp_path / "stockfish.exe"
    model.write_bytes(b"test model")
    engine.write_bytes(b"test engine")
    monkeypatch.setenv("CHESSLENS_MODEL_PATH", str(model))
    monkeypatch.setenv("CHESSLENS_ENGINE_PATH", str(engine))
    assert launcher.configuration(None, None) == (model.resolve(), engine.resolve())
    with pytest.raises(ValueError, match="Model not found"):
        launcher.configuration(tmp_path / "absent.pt", engine)


def test_bundled_model_tampering_is_rejected(tmp_path, monkeypatch):
    model = tmp_path / "piece_classifier.pt"
    model.write_bytes(b"changed")
    (tmp_path / "model.json").write_text('{"sha256":"wrong"}')
    monkeypatch.setattr(launcher, "BUNDLED_MODEL", model)
    monkeypatch.setattr(launcher, "ASSETS", tmp_path)
    with pytest.raises(ValueError, match="checksum mismatch"):
        launcher.check_model(model)


def test_doctor_checks_configuration_without_starting_server(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "configuration", lambda *args: (Path("model.pt"), Path("engine")))
    monkeypatch.setattr(launcher, "probe_engine", lambda path: "Test UCI")
    launcher.main(["--doctor", "--no-browser"])
    assert "Engine ready: Test UCI" in capsys.readouterr().out


def test_invalid_port_and_missing_engine_are_actionable(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        launcher.main(["--port", "80"])
    assert "1024" in capsys.readouterr().err
    monkeypatch.setattr("image2pgn.analyze.resolve_engine_path", lambda path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.delenv("CHESSLENS_ENGINE_PATH", raising=False)
    monkeypatch.delenv("CHESSLENS_MODEL_PATH", raising=False)
    with pytest.raises(ValueError, match="--engine PATH"):
        launcher.configuration(None, None)


def test_browser_only_opens_after_server_ready(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.webbrowser, "open", calls.append)
    launcher.open_when_ready(SimpleNamespace(started=True, should_exit=False), "http://127.0.0.1:8771/")
    assert calls == ["http://127.0.0.1:8771/"]


def test_integrated_root_keeps_security_and_legacy_workspace(tmp_path):
    with TestClient(webapp.create_app()) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="image" type="file"' in response.text
        assert 'id="master-connection"' in response.text
        assert 'id="compare-move"' in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/workspace").status_code == 200
        assert client.get("/", headers={"Host": "example.com"}).status_code == 403
        assert client.get("/assets/pieces/wk.svg").status_code == 200
        assert client.get("/assets/fonts/PretendardVariable.woff2").status_code == 200
