# Bundled experimental piece classifier

`piece_classifier.pt` is a small PieceCNN checkpoint included so a clean checkout
can recognize PNG/JPEG screenshots without finding an ignored local model file.
It contains only the model state tensors and class names. No source screenshots,
credentials, experiment paths, or optimizer state are included in the checkpoint.

- Source experiment: project UI-negative training, fixed epoch 8 (2026-09-10).
- Input: a 96×96 crop for each board square; 13 piece/empty classes.
- Source and packaged file SHA-256 values are recorded in `model.json`.
- Training lineage: the project's existing target-style/class-folder data and
  synthetic UI-negative experiment. This is an experimental artifact; no new
  independent evaluation is claimed by publishing it.
- Limits: unfamiliar themes, overlays, board alignment, small pieces, and piece
  colors can be wrong. Review every position and its game-state fields before
  analysis. A high per-square score is not a guarantee of a correct board.

Earlier training notes live in [MODEL_HISTORY.md](../../MODEL_HISTORY.md) and
[archived workflows](../../docs/legacy-workflows.md). Their development scores
are not an accuracy guarantee for this checkpoint or new user images.

Use `--model PATH` or `CHESSLENS_MODEL_PATH` for another compatible checkpoint.
Stockfish is installed separately; it is not inside this model or repository.
