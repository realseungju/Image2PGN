"""Open only the local ChessLens explanation page in a constrained desktop shell."""
from pathlib import Path
import json
import os
import subprocess


def open_popup(job_id, source_bounds=None):
    root = Path(__file__).resolve().parents[1]
    default = root.parent / 'shared-brain/research/frieren-companion/desktop/node_modules/electron/dist/electron.exe'
    executable = Path(os.environ.get('CHESSLENS_ELECTRON_PATH', str(default)))
    if not executable.is_file():
        raise FileNotFoundError('Electron runtime not configured')
    env = os.environ.copy()
    env['CHESSLENS_SOURCE_BOUNDS'] = json.dumps(source_bounds)
    subprocess.Popen([str(executable), str(root/'desktop/main.cjs'), '--job='+job_id], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
