# Model History

This document tracks the CNN model experiments for Image2PGN.

## Current Baseline

Use this model:

```text
models/piece_cnn_target_mix.pt
```

Recommended inference command:

```powershell
C:\Users\reals\Documents\Workspace\.venv\Scripts\python.exe -m image2pgn fen-cnn `
  --image image\chess_img.jpg `
  --model models\piece_cnn_target_mix.pt `
  --orientation auto `
  --device cuda `
  --threshold 0.5
```

Important: do **not** use `--infer-color-from-image` with this model by default.
The model already learned piece color well enough, and the brightness-based
color postprocess flipped some white pieces to black.
`--orientation auto` is recommended for screenshots when the board may be shown
from either White's or Black's side.

## Final Sample Result

Input:

```text
image/chess_img.jpg
```

Prediction:

```text
rnb1k1r1/1p3p1p/2p2p2/1q2p3/p2pP1P1/2bP1P1N/P1P1Q2P/2KR1BNR w - - 0 1
```

This matched the expected FEN for the sample image.

## Model Timeline

### `piece_cnn.pt`

Initial CNN model trained on the first converted dataset.

Result:

- Model saved successfully.
- Validation looked reasonable on the dataset.
- Actual sample image still failed badly because of domain gap.

Main issue:

```text
The model saw dataset styles, but not enough target chess.com-like board crops.
```

### `piece_cnn_v2.pt`

Trained after adding more data, including:

- Hugging Face YOLO chess board crops
- Kaggle piece crop data
- Hugging Face ChessVision square classification data

Validation:

```text
dataset_hf/val accuracy: 0.9845
```

But the real sample image was still poor. The validation set did not represent
the target screenshot style well enough.

### `piece_cnn_synth.pt`

Trained only on synthetic data generated from `dataset_hf/train` sprites.

Validation:

```text
dataset_synth/val accuracy: 0.9991
dataset_hf/val accuracy: 0.7543
```

Result:

- Excellent on synthetic data.
- Worse on original validation and actual sample image.

Main issue:

```text
Synthetic-only training caused the model to overfit synthetic artifacts and
forget the broader dataset distribution.
```

### `piece_cnn_mix.pt`

Trained with:

```text
dataset_hf + dataset_synth
```

Validation:

```text
dataset_hf/val accuracy:    0.8161
dataset_synth/val accuracy: 0.8469
combined val accuracy:      0.8440
```

Result:

- Still not good enough.
- Empty squares were frequently misclassified as black knight or black king.

Main issue:

```text
The synthetic data generated from generic sprites introduced confusing empty
and coordinate/background artifacts.
```

### `piece_cnn_target_mix.pt`

Current best model.

Trained with:

```text
dataset_hf + dataset_synth_target
```

Where `dataset_synth_target` was generated from `dataset/train`, which came from
the target sample image style.

Generation command:

```powershell
C:\Users\reals\Documents\Workspace\.venv\Scripts\python.exe -m image2pgn generate-synthetic `
  --out dataset_synth_target `
  --sprites dataset\train `
  --positions 500 `
  --styles chesscom_green,chesscom_brown,lichess_brown,lichess_blue,lichess_gray `
  --split train `
  --progress-every 50

C:\Users\reals\Documents\Workspace\.venv\Scripts\python.exe -m image2pgn generate-synthetic `
  --out dataset_synth_target `
  --sprites dataset\train `
  --positions 100 `
  --styles chesscom_green,chesscom_brown,lichess_brown,lichess_blue,lichess_gray `
  --split val `
  --seed 123 `
  --progress-every 25
```

Training command:

```powershell
C:\Users\reals\Documents\Workspace\.venv\Scripts\python.exe -m image2pgn train-cnn `
  --data dataset_hf `
  --extra-data dataset_synth_target `
  --model models\piece_cnn_target_mix.pt `
  --epochs 12 `
  --batch-size 128 `
  --device cuda `
  --progress-every 100
```

Validation:

```text
split=val total=7047 correct=7038 accuracy=0.9987
```

Per-class highlights:

```text
empty:        1.0000
white_rook:   1.0000
black_pawn:   1.0000
black_queen:  1.0000
black_king:   0.9922
white_queen:  0.9891
```

Final sample result matched the expected FEN when `--infer-color-from-image` was
not used.

## Lessons Learned

1. Dataset validation accuracy is not enough if the validation set does not
   represent the target screenshot style.
2. Synthetic data is useful, but sprite source matters.
3. Synthetic data generated from generic sprites did not help enough.
4. Synthetic data generated from the target-style crop source worked much better.
5. Brightness-based color postprocessing is useful as a fallback, but should not
   be enabled by default once the CNN learns color reliably.
6. The current best inference path is CNN-only color prediction with
   `--threshold 0.5`.

## Next Steps

- Add more target-style screenshots with known FEN.
- Generate more `dataset_synth_target` from those screenshots.
- Keep a small target validation set separate from training data.
- Evaluate future models on:

```text
dataset_hf/val
dataset_synth_target/val
real target screenshots
```
