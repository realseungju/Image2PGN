# Image2PGN

Chess board image recognition prototype.

Current scope: **stage 1, board image -> FEN**.

This first implementation targets clean chessboard images such as screenshots or
well-framed board photos. PGN requires move history, so this stage outputs FEN.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Quick Start

The recognizer uses template matching. First teach it a board style from an image
with a known FEN:

```powershell
python -m image2pgn learn `
  --image samples/start.png `
  --fen "rn1qkbnr/pppbpppp/8/3p4/8/2N5/PPPPPPPP/R1BQKBNR" `
  --templates templates/default
```

Then recognize another image using those templates:

```powershell
python -m image2pgn fen `
  --image samples/position.png `
  --templates templates/default
```

This prints a full FEN with default metadata:

```text
<piece-placement> w - - 0 1
```

Use `--placement-only` if you only want the first FEN field.

Optional debug output:

```powershell
python -m image2pgn fen --image samples/position.png --templates templates/default --debug-dir debug
```

## Board Orientation

By default the output assumes White is at the bottom. If the image is from
Black's side, add:

```powershell
--orientation black
```

## Limitations

- The current classifier is template-based, not a trained OCR/CV model.
- It works best when the input board style matches the learned templates.
- For real offline photos, the next steps are stronger board detection,
  larger labeled data, and a learned piece classifier.

## CNN Classifier Workflow

For recognizing new board styles, build a square-level dataset from labeled board
images, then train a CNN classifier.

Create 64 labeled square crops from a board image:

```powershell
python -m image2pgn make-dataset `
  --image image/chess_img.jpg `
  --fen "rnb1k1r1/1p3p1p/2p2p2/1q2p3/p2pP1P1/2bP1P1N/P1P1Q2P/2KR1BNR" `
  --orientation black `
  --out dataset `
  --split train
```

Install PyTorch before training:

```powershell
python -m pip install -r requirements-cnn.txt
```

Train:

```powershell
python -m image2pgn train-cnn `
  --data dataset `
  --model models/piece_cnn.pt `
  --epochs 12
```

Recognize with the trained CNN:

```powershell
python -m image2pgn fen-cnn `
  --image image/new_board.jpg `
  --model models/piece_cnn.pt `
  --orientation white `
  --threshold 0.8 `
  --infer-color-from-image
```

`--threshold` uses the CNN softmax confidence. Predictions below the threshold
are treated as empty squares, which helps reduce false piece detections.
`--infer-color-from-image` keeps the CNN's piece type prediction but rechecks
white/black from the square image brightness.

CNN recognition generalizes only as far as the data does. Add labeled examples
from many board themes, piece sets, colors, and camera conditions.

## Hugging Face YOLO Dataset

The downloaded Hugging Face zip files can be converted directly without fully
extracting them first:

```powershell
python -m image2pgn prepare-hf-yolo `
  --zip chess_yolo_data-20250419T135412Z-001.zip `
  --zip chess_yolo_data-20250419T135412Z-002.zip `
  --out dataset_hf `
  --empty-per-board 8 `
  --progress-every 500
```

For a quick smoke test, cap the number of board images:

```powershell
python -m image2pgn prepare-hf-yolo `
  --zip chess_yolo_data-20250419T135412Z-001.zip `
  --zip chess_yolo_data-20250419T135412Z-002.zip `
  --out dataset_hf_sample `
  --max-train-images 100 `
  --max-val-images 20 `
  --empty-per-board 8
```

Train from the converted dataset:

```powershell
python -m image2pgn train-cnn `
  --data dataset_hf `
  --model models/piece_cnn.pt `
  --epochs 12 `
  --batch-size 64 `
  --device cpu `
  --progress-every 100
```

Evaluate a trained model:

```powershell
python -m image2pgn eval-cnn `
  --data dataset_hf `
  --model models/piece_cnn.pt `
  --split val `
  --device cuda
```

The Hugging Face YOLO class ids are mapped as:

```text
0 white_pawn, 1 white_knight, 2 white_bishop, 3 white_rook, 4 white_queen, 5 white_king
6 black_pawn, 7 black_knight, 8 black_bishop, 9 black_rook, 10 black_queen, 11 black_king
```

## Adding Class-Folder Datasets

Datasets such as Kaggle piece crops can be merged into the same CNN dataset as
long as images are grouped by class folders. Folder names like `White Pawn`,
`white_pawn`, `white-pawn`, or `wp` are mapped automatically.

```powershell
python -m image2pgn import-class-dirs `
  --input kaggle_chess_data `
  --out dataset_hf `
  --split train `
  --val-ratio 0.1 `
  --infer-color-from-image
```

This appends images into `dataset_hf/train/<class>` and
`dataset_hf/val/<class>`. If the external dataset has no `empty` class, keep the
empty-square examples from `prepare-hf-yolo`. Use `--infer-color-from-image`
when the source folders contain piece type only, such as `bishop`, `king`, or
`pawn`.

## Adding Hugging Face Image Datasets

The ChessVision square-classification dataset provides 13 classes (`wP`, `bK`,
`xx`, etc.) and can be merged directly:

```powershell
python -m image2pgn import-hf-dataset `
  --name S1M0N38/chess-cv-chessvision `
  --out dataset_hf `
  --progress-every 500
```

This dataset is small but useful because it already includes white pieces, black
pieces, and empty squares in a classification-ready layout.

## Generating Synthetic Style Data

Synthetic data can expand board themes without downloading another labeled
dataset. It uses an existing class-folder dataset as piece sprites, then renders
new square crops with varied board colors, coordinates, highlights, brightness,
blur, and noise.

```powershell
python -m image2pgn generate-synthetic `
  --out dataset_synth `
  --sprites dataset_hf/train `
  --positions 5000 `
  --styles chesscom_green,lichess_brown `
  --split train `
  --progress-every 250
```

Available styles:

```text
chesscom_green, chesscom_brown, lichess_brown, lichess_blue, lichess_gray
```

For a quick validation set:

```powershell
python -m image2pgn generate-synthetic `
  --out dataset_synth `
  --sprites dataset_hf/train `
  --positions 500 `
  --styles chesscom_green,lichess_brown `
  --split val
```

Train with both the real/imported dataset and synthetic dataset:

```powershell
python -m image2pgn train-cnn `
  --data dataset_hf `
  --extra-data dataset_synth `
  --model models/piece_cnn_mix.pt `
  --epochs 12 `
  --batch-size 128 `
  --device cuda `
  --progress-every 100
```
