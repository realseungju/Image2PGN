from __future__ import annotations

import argparse
from pathlib import Path

from .analyze import analyze_fen, format_analysis
from .cnn import TrainConfig, evaluate_cnn, recognize_fen_cnn, recognize_fen_cnn_result, train_cnn
from .dataset import (
    import_class_folder_dataset,
    import_huggingface_image_dataset,
    make_dataset_from_hf_yolo_zips,
    make_dataset_from_labeled_board,
)
from .recognizer import learn_templates, recognize_fen
from .synthetic import STYLE_COLORS, SyntheticConfig, generate_synthetic_dataset
from .visualize import save_analysis_overlay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image2pgn",
        description="Recognize a chessboard image and output FEN.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    learn = subparsers.add_parser("learn", help="Create piece templates from a labeled board image.")
    learn.add_argument("--image", required=True, type=Path, help="Path to a labeled chessboard image.")
    learn.add_argument("--fen", required=True, help="Piece-placement FEN or full FEN for the image.")
    learn.add_argument("--templates", required=True, type=Path, help="Directory where templates are saved.")
    learn.add_argument(
        "--orientation",
        choices=("white", "black"),
        default="white",
        help="Side at the bottom of the input image.",
    )
    learn.add_argument("--debug-dir", type=Path, help="Optional directory for warped board/square previews.")

    fen = subparsers.add_parser("fen", help="Recognize a board image and print piece-placement FEN.")
    fen.add_argument("--image", required=True, type=Path, help="Path to a chessboard image.")
    fen.add_argument("--templates", required=True, type=Path, help="Directory containing learned templates.")
    fen.add_argument(
        "--orientation",
        choices=("white", "black"),
        default="white",
        help="Side at the bottom of the input image.",
    )
    fen.add_argument(
        "--threshold",
        type=float,
        default=0.58,
        help="Minimum template similarity for accepting a piece.",
    )
    fen.add_argument(
        "--side-to-move",
        choices=("w", "b"),
        default="w",
        help="Side to move field for full FEN output.",
    )
    fen.add_argument(
        "--castling",
        default="-",
        help="Castling availability field for full FEN output.",
    )
    fen.add_argument(
        "--en-passant",
        default="-",
        help="En-passant target square field for full FEN output.",
    )
    fen.add_argument(
        "--halfmove",
        type=int,
        default=0,
        help="Halfmove clock field for full FEN output.",
    )
    fen.add_argument(
        "--fullmove",
        type=int,
        default=1,
        help="Fullmove number field for full FEN output.",
    )
    fen.add_argument(
        "--placement-only",
        action="store_true",
        help="Print only the piece-placement field instead of full FEN.",
    )
    fen.add_argument("--debug-dir", type=Path, help="Optional directory for warped board/square previews.")

    dataset = subparsers.add_parser(
        "make-dataset",
        help="Create square-level CNN training images from a labeled board image.",
    )
    dataset.add_argument("--image", required=True, type=Path, help="Path to a labeled chessboard image.")
    dataset.add_argument("--fen", required=True, help="Piece-placement FEN or full FEN for the image.")
    dataset.add_argument("--out", required=True, type=Path, help="Dataset output directory.")
    dataset.add_argument(
        "--split",
        choices=("train", "val", "test"),
        default="train",
        help="Dataset split to write into.",
    )
    dataset.add_argument(
        "--orientation",
        choices=("white", "black"),
        default="white",
        help="Side at the bottom of the input image.",
    )
    dataset.add_argument("--debug-dir", type=Path, help="Optional directory for warped board/square previews.")

    hf_dataset = subparsers.add_parser(
        "prepare-hf-yolo",
        help="Convert Hugging Face chess_yolo_data zip files into CNN square crops.",
    )
    hf_dataset.add_argument(
        "--zip",
        dest="zip_paths",
        action="append",
        required=True,
        type=Path,
        help="Path to a chess_yolo_data zip. Pass this option multiple times.",
    )
    hf_dataset.add_argument("--out", required=True, type=Path, help="Dataset output directory.")
    hf_dataset.add_argument(
        "--max-train-images",
        type=int,
        help="Optional cap for train board images. Omit to process all train images.",
    )
    hf_dataset.add_argument(
        "--max-val-images",
        type=int,
        help="Optional cap for validation board images. Omit to process all val images.",
    )
    hf_dataset.add_argument(
        "--empty-per-board",
        type=int,
        default=8,
        help="Number of empty squares to sample per board image.",
    )
    hf_dataset.add_argument("--seed", type=int, default=42, help="Random seed for empty-square sampling.")
    hf_dataset.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Print conversion progress every N board images. Use 0 to disable.",
    )

    class_dirs = subparsers.add_parser(
        "import-class-dirs",
        help="Import a class-folder image dataset into the CNN dataset layout.",
    )
    class_dirs.add_argument("--input", required=True, type=Path, help="Root folder containing class subfolders.")
    class_dirs.add_argument("--out", required=True, type=Path, help="Dataset output directory.")
    class_dirs.add_argument(
        "--split",
        choices=("train", "val", "test"),
        default="train",
        help="Default split to write imported images into.",
    )
    class_dirs.add_argument(
        "--val-ratio",
        type=float,
        default=0.0,
        help="When split=train, reserve this fraction of each class for val.",
    )
    class_dirs.add_argument("--seed", type=int, default=42, help="Random seed for train/val splitting.")
    class_dirs.add_argument("--max-per-class", type=int, help="Optional cap per class.")
    class_dirs.add_argument(
        "--infer-color-from-image",
        action="store_true",
        help="For type-only folders like pawn/rook, infer white/black from image brightness.",
    )

    hf_image = subparsers.add_parser(
        "import-hf-dataset",
        help="Import a Hugging Face image-classification dataset into the CNN dataset layout.",
    )
    hf_image.add_argument("--name", required=True, help="Hugging Face dataset name, e.g. owner/dataset.")
    hf_image.add_argument("--out", required=True, type=Path, help="Dataset output directory.")
    hf_image.add_argument("--train-split", default="train", help="Source training split name.")
    hf_image.add_argument("--val-split", default="validation", help="Source validation split name.")
    hf_image.add_argument("--max-train", type=int, help="Optional cap for train rows.")
    hf_image.add_argument("--max-val", type=int, help="Optional cap for validation rows.")
    hf_image.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Print import progress every N rows. Use 0 to disable.",
    )

    synthetic = subparsers.add_parser(
        "generate-synthetic",
        help="Generate style-varied synthetic square crops from existing piece sprites.",
    )
    synthetic.add_argument("--out", required=True, type=Path, help="Synthetic dataset output directory.")
    synthetic.add_argument(
        "--sprites",
        type=Path,
        default=Path("dataset_hf/train"),
        help="Class-folder dataset used as piece sprite source.",
    )
    synthetic.add_argument("--positions", type=int, default=5000, help="Number of synthetic boards to generate.")
    synthetic.add_argument(
        "--styles",
        default="chesscom_green,lichess_brown",
        help=f"Comma-separated styles. Available: {','.join(sorted(STYLE_COLORS))}",
    )
    synthetic.add_argument(
        "--split",
        choices=("train", "val", "test"),
        default="train",
        help="Dataset split to write into.",
    )
    synthetic.add_argument("--square-size", type=int, default=96, help="Output square size in pixels.")
    synthetic.add_argument("--seed", type=int, default=42, help="Random seed.")
    synthetic.add_argument("--coords-probability", type=float, default=0.45, help="Probability of drawing coordinates.")
    synthetic.add_argument("--highlight-probability", type=float, default=0.18, help="Probability of highlighted squares.")
    synthetic.add_argument("--progress-every", type=int, default=250, help="Print progress every N boards.")

    train = subparsers.add_parser("train-cnn", help="Train a CNN square classifier.")
    train.add_argument("--data", required=True, type=Path, help="Dataset directory containing train/ and optional val/.")
    train.add_argument(
        "--extra-data",
        action="append",
        default=[],
        type=Path,
        help="Additional dataset directory to mix into training/evaluation. Can be passed multiple times.",
    )
    train.add_argument("--model", required=True, type=Path, help="Output .pt model path.")
    train.add_argument("--epochs", type=int, default=12, help="Number of training epochs.")
    train.add_argument("--batch-size", type=int, default=32, help="Training batch size.")
    train.add_argument("--lr", type=float, default=0.001, help="Learning rate.")
    train.add_argument("--device", default="auto", help="auto, cpu, cuda, or a PyTorch device string.")
    train.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print training progress every N batches. Use 0 to disable.",
    )

    eval_cnn = subparsers.add_parser("eval-cnn", help="Evaluate a trained CNN model on a dataset split.")
    eval_cnn.add_argument("--data", required=True, type=Path, help="Dataset directory containing split folders.")
    eval_cnn.add_argument(
        "--extra-data",
        action="append",
        default=[],
        type=Path,
        help="Additional dataset directory to include in evaluation. Can be passed multiple times.",
    )
    eval_cnn.add_argument("--model", required=True, type=Path, help="Trained CNN .pt model path.")
    eval_cnn.add_argument("--split", default="val", help="Dataset split to evaluate, usually val or train.")
    eval_cnn.add_argument("--batch-size", type=int, default=128, help="Evaluation batch size.")
    eval_cnn.add_argument("--device", default="auto", help="auto, cpu, cuda, or a PyTorch device string.")
    eval_cnn.add_argument("--top-mistakes", type=int, default=10, help="Number of confusion pairs to print.")

    fen_cnn = subparsers.add_parser("fen-cnn", help="Recognize a board image with a trained CNN model.")
    fen_cnn.add_argument("--image", required=True, type=Path, help="Path to a chessboard image.")
    fen_cnn.add_argument("--model", required=True, type=Path, help="Trained CNN .pt model path.")
    fen_cnn.add_argument(
        "--orientation",
        choices=("white", "black", "auto"),
        default="white",
        help="Side at the bottom of the input image.",
    )
    fen_cnn.add_argument("--device", default="auto", help="auto, cpu, cuda, or a PyTorch device string.")
    fen_cnn.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum softmax confidence for accepting a piece. Lower-confidence squares become empty.",
    )
    fen_cnn.add_argument(
        "--infer-color-from-image",
        action="store_true",
        help="Keep the predicted piece type but infer white/black from square pixel brightness.",
    )
    fen_cnn.add_argument(
        "--side-to-move",
        choices=("w", "b"),
        default="w",
        help="Side to move field for full FEN output.",
    )
    fen_cnn.add_argument("--castling", default="-", help="Castling availability field for full FEN output.")
    fen_cnn.add_argument("--en-passant", default="-", help="En-passant target square field for full FEN output.")
    fen_cnn.add_argument("--halfmove", type=int, default=0, help="Halfmove clock field for full FEN output.")
    fen_cnn.add_argument("--fullmove", type=int, default=1, help="Fullmove number field for full FEN output.")
    fen_cnn.add_argument(
        "--placement-only",
        action="store_true",
        help="Print only the piece-placement field instead of full FEN.",
    )
    fen_cnn.add_argument("--debug-dir", type=Path, help="Optional directory for warped board/square previews.")

    analyze_fen_parser = subparsers.add_parser("analyze-fen", help="Analyze a FEN with a UCI chess engine.")
    analyze_fen_parser.add_argument("--fen", required=True, help="Full FEN to analyze.")
    analyze_fen_parser.add_argument("--engine", type=Path, help="Path to a UCI engine executable.")
    analyze_fen_parser.add_argument("--depth", type=int, default=14, help="Engine search depth.")
    analyze_fen_parser.add_argument("--movetime-ms", type=int, help="Use fixed engine time instead of depth.")
    analyze_fen_parser.add_argument("--top", type=int, default=5, help="Number of candidate moves to show.")

    analyze_image = subparsers.add_parser("analyze-image", help="Recognize a screenshot FEN and analyze it.")
    analyze_image.add_argument("--image", required=True, type=Path, help="Path to a chessboard image.")
    analyze_image.add_argument("--model", required=True, type=Path, help="Trained CNN .pt model path.")
    analyze_image.add_argument(
        "--orientation",
        choices=("white", "black", "auto"),
        default="auto",
        help="Side at the bottom of the input image.",
    )
    analyze_image.add_argument("--device", default="auto", help="auto, cpu, cuda, or a PyTorch device string.")
    analyze_image.add_argument("--threshold", type=float, default=0.5, help="CNN confidence threshold.")
    analyze_image.add_argument("--side-to-move", choices=("w", "b"), default="w", help="Side to move for analysis.")
    analyze_image.add_argument(
        "--infer-color-from-image",
        action="store_true",
        help="Fallback color correction based on square brightness.",
    )
    analyze_image.add_argument("--debug-dir", type=Path, help="Optional directory for warped board/square previews.")
    analyze_image.add_argument("--engine", type=Path, help="Path to a UCI engine executable.")
    analyze_image.add_argument("--depth", type=int, default=14, help="Engine search depth.")
    analyze_image.add_argument("--movetime-ms", type=int, help="Use fixed engine time instead of depth.")
    analyze_image.add_argument("--top", type=int, default=5, help="Number of candidate moves to show.")
    analyze_image.add_argument("--visual-out", type=Path, help="Optional PNG path for a static visual analysis overlay.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "learn":
        count = learn_templates(
            image_path=args.image,
            fen=args.fen,
            template_dir=args.templates,
            orientation=args.orientation,
            debug_dir=args.debug_dir,
        )
        print(f"saved {count} templates to {args.templates}")
        return

    if args.command == "fen":
        placement = recognize_fen(
            image_path=args.image,
            template_dir=args.templates,
            orientation=args.orientation,
            threshold=args.threshold,
            debug_dir=args.debug_dir,
        )
        if args.placement_only:
            print(placement)
        else:
            print(
                f"{placement} {args.side_to_move} {args.castling} "
                f"{args.en_passant} {args.halfmove} {args.fullmove}"
            )
        return

    if args.command == "make-dataset":
        count = make_dataset_from_labeled_board(
            image_path=args.image,
            fen=args.fen,
            out_dir=args.out,
            split=args.split,
            orientation=args.orientation,
            debug_dir=args.debug_dir,
        )
        print(f"saved {count} square images to {args.out / args.split}")
        return

    if args.command == "prepare-hf-yolo":
        counts = make_dataset_from_hf_yolo_zips(
            zip_paths=args.zip_paths,
            out_dir=args.out,
            max_train_images=args.max_train_images,
            max_val_images=args.max_val_images,
            empty_per_board=args.empty_per_board,
            seed=args.seed,
            progress_every=args.progress_every,
        )
        for key in sorted(counts):
            print(f"{key}: {counts[key]}")
        return

    if args.command == "import-class-dirs":
        counts = import_class_folder_dataset(
            input_dir=args.input,
            out_dir=args.out,
            split=args.split,
            val_ratio=args.val_ratio,
            seed=args.seed,
            max_per_class=args.max_per_class,
            infer_color_from_image=args.infer_color_from_image,
        )
        for key in sorted(counts):
            print(f"{key}: {counts[key]}")
        return

    if args.command == "import-hf-dataset":
        counts = import_huggingface_image_dataset(
            dataset_name=args.name,
            out_dir=args.out,
            train_split=args.train_split,
            val_split=args.val_split,
            max_train=args.max_train,
            max_val=args.max_val,
            progress_every=args.progress_every,
        )
        for key in sorted(counts):
            print(f"{key}: {counts[key]}")
        return

    if args.command == "generate-synthetic":
        styles = tuple(style.strip() for style in args.styles.split(",") if style.strip())
        unknown = [style for style in styles if style not in STYLE_COLORS]
        if unknown:
            parser.error(f"unknown style(s): {', '.join(unknown)}")
        counts = generate_synthetic_dataset(
            SyntheticConfig(
                out_dir=args.out,
                sprites_dir=args.sprites,
                positions=args.positions,
                split=args.split,
                styles=styles,
                square_size=args.square_size,
                seed=args.seed,
                coords_probability=args.coords_probability,
                highlight_probability=args.highlight_probability,
                progress_every=args.progress_every,
            )
        )
        for key in sorted(counts):
            print(f"{key}: {counts[key]}")
        return

    if args.command == "train-cnn":
        train_cnn(
            TrainConfig(
                data_dir=args.data,
                model_path=args.model,
                extra_data_dirs=tuple(args.extra_data),
                epochs=args.epochs,
                batch_size=args.batch_size,
                learning_rate=args.lr,
                device=args.device,
                progress_every=args.progress_every,
            )
        )
        print(f"saved model to {args.model}")
        return

    if args.command == "eval-cnn":
        result = evaluate_cnn(
            data_dir=args.data,
            extra_data_dirs=tuple(args.extra_data),
            model_path=args.model,
            split=args.split,
            device=args.device,
            batch_size=args.batch_size,
        )
        print(
            f"split={result['split']} total={result['total']} "
            f"correct={result['correct']} accuracy={result['accuracy']:.4f}"
        )
        print("per-class:")
        for class_name, metrics in sorted(result["per_class"].items()):
            print(
                f"  {class_name}: support={metrics['support']} "
                f"correct={metrics['correct']} accuracy={metrics['accuracy']:.4f}"
            )
        if args.top_mistakes > 0:
            print("top mistakes:")
            for count, truth_name, pred_name in result["mistakes"][: args.top_mistakes]:
                print(f"  {truth_name} -> {pred_name}: {count}")
        return

    if args.command == "fen-cnn":
        placement = recognize_fen_cnn(
            image_path=args.image,
            model_path=args.model,
            orientation=args.orientation,
            device=args.device,
            debug_dir=args.debug_dir,
            threshold=args.threshold,
            infer_color_from_image=args.infer_color_from_image,
        )
        if args.placement_only:
            print(placement)
        else:
            print(
                f"{placement} {args.side_to_move} {args.castling} "
                f"{args.en_passant} {args.halfmove} {args.fullmove}"
            )
        return

    if args.command == "analyze-fen":
        analysis = analyze_fen(
            fen=args.fen,
            engine_path=args.engine,
            depth=args.depth,
            top=args.top,
            movetime_ms=args.movetime_ms,
        )
        print(format_analysis(analysis))
        return

    if args.command == "analyze-image":
        recognition = recognize_fen_cnn_result(
            image_path=args.image,
            model_path=args.model,
            orientation=args.orientation,
            device=args.device,
            debug_dir=args.debug_dir,
            threshold=args.threshold,
            infer_color_from_image=args.infer_color_from_image,
        )
        fen = f"{recognition.placement} {args.side_to_move} - - 0 1"
        analysis = analyze_fen(
            fen=fen,
            engine_path=args.engine,
            depth=args.depth,
            top=args.top,
            movetime_ms=args.movetime_ms,
        )
        print(format_analysis(analysis))
        if args.visual_out is not None:
            save_analysis_overlay(
                image_path=args.image,
                analysis=analysis,
                orientation=recognition.orientation,
                output_path=args.visual_out,
            )
            print(f"visual saved to {args.visual_out}")
        return

    parser.error(f"unknown command: {args.command}")
