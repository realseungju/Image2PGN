"""Build the end-user ZIP from a committed revision, including its dependency lock."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ".python-version", "pyproject.toml", "uv.lock", "MANIFEST.in", "Start-ChessLens.cmd",
    "README.md", "README.ko.md", "MODEL_HISTORY.md", "docs", "desktop",
    "image/chess_img4.png", "image2pgn",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    project = subprocess.check_output(["git", "show", f"{revision}:pyproject.toml"], cwd=ROOT)
    version = tomllib.loads(project.decode("utf-8"))["project"]["version"]
    name = f"chesslens-{version}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{name}.zip"
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        staged = Path(tmp) / archive.name
        subprocess.run([
            "git", "archive", "--format=zip", f"--prefix={name}/", f"--output={staged}",
            revision, "--", *FILES,
        ], cwd=ROOT, check=True)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        staged.replace(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"{archive} ({revision[:12]}, SHA-256 {digest})")


if __name__ == "__main__":
    main()
