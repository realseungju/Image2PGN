"""python -m image2pgn.companion --port 8771 (loopback only)."""
import argparse
import os
from pathlib import Path
import uvicorn

from .webapp import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8771)
    parser.add_argument('--model', type=Path, default=Path(__file__).resolve().parents[1]/'models/piece_cnn_target_mix.pt')
    parser.add_argument('--engine', type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    os.environ['CHESSLENS_PORT'] = str(args.port)
    uvicorn.run(create_app(args.model, args.engine), host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
