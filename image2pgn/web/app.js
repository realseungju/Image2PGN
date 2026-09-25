const PIECES = [".", "K", "Q", "R", "B", "N", "P", "k", "q", "r", "b", "n", "p"];
const SYMBOLS = {
  ".": "×",
  K: "♚", Q: "♛", R: "♜", B: "♝", N: "♞", P: "♟",
  k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟",
};
const THEME_LABELS = {
  "wins or trades material": "Material gain or trade",
  "forces check": "Forcing check",
  "improves king safety": "King safety",
  "develops a minor piece": "Minor-piece development",
  "fights for the center": "Center control",
  "opens lines with a pawn break": "Pawn break",
  "increases heavy-piece activity": "Heavy-piece activity",
  "adds pressure near the enemy king": "King-side pressure",
  "creates a fork threat": "Fork threat",
  "creates or increases a pin": "Pin pressure",
  "threatens checkmate next move": "Mate threat",
};

let board = Array.from({ length: 8 }, () => Array(8).fill("."));
let selectedPiece = ".";
let sourceFile = null;
let sourceUrl = null;

function expandPlacement(placement) {
  const ranks = placement.trim().split("/");
  if (ranks.length !== 8) throw new Error("FEN must contain eight ranks.");
  return ranks.map((rank) => {
    const row = [];
    for (const char of rank) {
      if (/[1-8]/.test(char)) row.push(...Array(Number(char)).fill("."));
      else if (/[prnbqkPRNBQK]/.test(char)) row.push(char);
      else throw new Error("FEN contains an unsupported character.");
    }
    if (row.length !== 8) throw new Error("Every FEN rank must contain eight squares.");
    return row;
  });
}

function compressBoard(value) {
  return value.map((row) => {
    let output = "";
    let empty = 0;
    for (const piece of row) {
      if (piece === ".") {
        empty += 1;
        continue;
      }
      if (empty) {
        output += empty;
        empty = 0;
      }
      output += piece;
    }
    return output + (empty || "");
  }).join("/");
}

function rotateBoard(value) {
  return value.slice().reverse().map((row) => row.slice().reverse());
}

function qs(id) {
  return document.getElementById(id);
}

function showToast(message, error = false) {
  const toast = qs("toast");
  toast.textContent = message;
  toast.className = `toast${error ? " error" : ""}`;
  setTimeout(() => toast.classList.add("hidden"), 4500);
}

function formatBytes(bytes) {
  return bytes < 1048576
    ? `${(bytes / 1024).toFixed(1)} KiB`
    : `${(bytes / 1048576).toFixed(1)} MiB`;
}

function fullFen() {
  return `${compressBoard(board)} ${qs("side").value} ${qs("castling").value.trim() || "-"} ${qs("en-passant").value.trim() || "-"} ${qs("halfmove").value || 0} ${qs("fullmove").value || 1}`;
}

function syncFen() {
  qs("placement").value = compressBoard(board);
  qs("full-fen").textContent = fullFen();
}

function analysisSummary(result) {
  const best = result.moves?.[0];
  if (!best) return result.evaluation === "game over" ? "The game is already over." : "Stockfish returned no candidate moves.";
  if (best.mate !== null && best.mate !== undefined) {
    return best.mate > 0
      ? `There is a forced mate. ${best.san} is the first move.`
      : `${best.san} is the best defense, but a mating threat remains.`;
  }
  if (best.score_cp === null || best.score_cp === undefined) return `${best.san} is Stockfish's top choice.`;
  const centipawns = best.score_cp;
  const status = centipawns >= 150
    ? "a clear advantage"
    : centipawns >= 50
      ? "a small advantage"
      : centipawns > -50
        ? "a balanced position"
        : centipawns > -150
          ? "a slightly worse position"
          : "a position in serious danger";
  return `${best.san} is Stockfish's top choice. From the side-to-move perspective, this is ${status}.`;
}

function themeLabel(theme) {
  return THEME_LABELS[theme] || theme;
}

function deltaLabel(delta) {
  if (delta === "best-eval") return "Best";
  const match = /^([+-]\d+\.\d+) vs best$/.exec(delta);
  return match ? `${match[1]} vs best` : delta;
}

function noticeLabel(value) {
  return value;
}

function pieceMark(piece) {
  if (piece === ".") return null;
  const mark = document.createElement("span");
  mark.className = `piece ${piece === piece.toUpperCase() ? "white-piece" : "black-piece"}`;
  mark.textContent = SYMBOLS[piece];
  return mark;
}

function renderBoard() {
  const root = qs("chessboard");
  root.innerHTML = "";
  board.forEach((row, rank) => row.forEach((piece, file) => {
    const square = document.createElement("button");
    square.type = "button";
    square.className = `square ${(rank + file) % 2 ? "dark" : "light"}`;
    square.setAttribute("aria-label", `${String.fromCharCode(97 + file)}${8 - rank} ${piece === "." ? "empty" : piece}`);
    const mark = pieceMark(piece);
    if (mark) square.append(mark);
    square.addEventListener("click", () => {
      board[rank][file] = selectedPiece;
      renderBoard();
      syncFen();
    });
    root.append(square);
  }));
}

function renderPalette() {
  const root = qs("piece-palette");
  root.innerHTML = "";
  PIECES.forEach((piece) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `piece-choice${piece === selectedPiece ? " selected" : ""}`;
    button.setAttribute("aria-label", piece === "." ? "Erase piece" : `Select ${piece}`);
    if (piece === ".") button.textContent = "×";
    else button.append(pieceMark(piece));
    button.addEventListener("click", () => {
      selectedPiece = piece;
      renderPalette();
    });
    root.append(button);
  });
}

function resetForNewFile() {
  qs("upload-stage").classList.remove("hidden");
  qs("review-section").classList.add("hidden");
  qs("analysis-empty").classList.remove("hidden");
  qs("analysis-setup").classList.add("hidden");
  qs("result-section").classList.add("hidden");
  qs("normalized-preview").classList.add("hidden");
  qs("confirm-history").checked = false;
  qs("analyze-button").disabled = true;
}

function setFile(file) {
  if (!file) return;
  sourceFile = file;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = URL.createObjectURL(file);
  qs("source-preview").src = sourceUrl;
  qs("file-name").textContent = file.name;
  qs("file-size").textContent = formatBytes(file.size);
  qs("upload-preview").classList.remove("hidden");
  qs("recognize-button").classList.remove("hidden");
  resetForNewFile();
}

async function recognize() {
  if (!sourceFile) return showToast("Choose an image first.", true);
  document.body.classList.add("loading");
  qs("recognize-button").innerHTML = "Detecting… <span>⌛</span>";
  try {
    const data = new FormData();
    data.append("image", sourceFile);
    const response = await fetch("/api/recognize", { method: "POST", body: data });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Board detection failed.");

    board = expandPlacement(result.placement);
    renderBoard();
    syncFen();
    qs("normalized-board").src = result.board_image;
    qs("normalized-preview").classList.remove("hidden");

    const details = result.board_details || {};
    const bounds = (details.bounds || []).join(", ") || "manual review needed";
    qs("detection-copy").textContent = `${details.method || "unknown detector"} · bounds ${bounds}`;

    const badges = qs("recognition-badges");
    badges.innerHTML = "";
    [
      [`${result.orientation || "unknown"} orientation`, result.orientation_status === "uncertain"],
      [details.method || "unknown detector", Boolean(details.requires_review)],
      [`${(result.review_squares || []).length} squares to review`, result.review_squares?.length > 0],
    ].forEach(([label, warning]) => {
      const badge = document.createElement("span");
      badge.className = `badge${warning ? " warn" : ""}`;
      badge.textContent = label;
      badges.append(badge);
    });

    const warnings = [];
    if (details.requires_review) warnings.push("The board boundary needs review. Compare the source and normalized board before analysis.");
    if (result.orientation_status === "uncertain") warnings.push("Board orientation is uncertain. Flip the board if needed.");
    if (result.review_squares?.length) warnings.push(`${result.review_squares.length} low-confidence squares need manual review.`);
    const warning = qs("recognition-warning");
    warning.textContent = warnings.join(" ");
    warning.classList.toggle("hidden", !warnings.length);

    qs("upload-stage").classList.add("hidden");
    qs("review-section").classList.remove("hidden");
    qs("analysis-empty").classList.add("hidden");
    qs("analysis-setup").classList.remove("hidden");
    qs("result-section").classList.add("hidden");
    qs("review-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showToast(error.message, true);
  } finally {
    document.body.classList.remove("loading");
    qs("recognize-button").innerHTML = "Detect board <span>→</span>";
  }
}

function renderAnalysis(result) {
  qs("evaluation").textContent = result.evaluation;
  qs("summary").textContent = analysisSummary(result);
  qs("result-fen").textContent = fullFen();
  const track = document.querySelector(".eval-track span");
  const score = Number(result.evaluation_cp || 0);
  track.style.width = `${Math.max(5, Math.min(95, 50 + Math.tanh(score / 400) * 45))}%`;

  const moves = qs("candidate-moves");
  moves.innerHTML = "";
  (result.moves || []).forEach((move) => {
    const card = document.createElement("div");
    card.className = "move-card";

    const rank = document.createElement("span");
    rank.className = "move-rank";
    rank.textContent = String(move.rank).padStart(2, "0");

    const san = document.createElement("strong");
    san.textContent = move.san;

    const main = document.createElement("div");
    main.className = "move-main";
    const pv = document.createElement("p");
    pv.textContent = `PV · ${move.pv_san.slice(0, 6).join(" ") || "—"}`;
    const themes = document.createElement("p");
    themes.textContent = move.themes.map(themeLabel).join(" · ") || "General improvement";
    main.append(pv, themes);

    const scoreBox = document.createElement("span");
    scoreBox.className = "move-score";
    scoreBox.append(document.createTextNode(move.score), document.createElement("br"));
    const delta = document.createElement("small");
    delta.textContent = deltaLabel(move.delta);
    scoreBox.append(delta);
    card.append(rank, san, main, scoreBox);
    moves.append(card);
  });
  if (!result.moves?.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No candidate moves returned.";
    moves.append(empty);
  }

  const notices = qs("threats");
  notices.innerHTML = "";
  [...(result.warnings || []), ...(result.threats || [])].forEach((text) => {
    const notice = document.createElement("div");
    notice.className = "notice";
    notice.textContent = noticeLabel(text);
    notices.append(notice);
  });
  if (!notices.children.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No immediate threats to display.";
    notices.append(empty);
  }

  qs("analysis-setup").classList.add("hidden");
  qs("result-section").classList.remove("hidden");
  qs("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyze() {
  document.body.classList.add("loading");
  qs("analyze-button").innerHTML = "Analyzing… <span>⌛</span>";
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fen: fullFen(), confirmed_history: qs("confirm-history").checked, top: 3, depth: 14 }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Stockfish analysis failed.");
    renderAnalysis(result);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    document.body.classList.remove("loading");
    qs("analyze-button").innerHTML = "Analyze with Stockfish <span>→</span>";
  }
}

function init() {
  renderPalette();
  renderBoard();
  syncFen();
  const input = qs("image-input");
  const dropzone = qs("dropzone");
  input.addEventListener("change", () => setFile(input.files[0]));
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag");
  }));
  dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));
  qs("recognize-button").addEventListener("click", recognize);
  qs("flip-button").addEventListener("click", () => {
    board = rotateBoard(board);
    renderBoard();
    syncFen();
  });
  qs("placement").addEventListener("change", (event) => {
    try {
      board = expandPlacement(event.target.value);
      renderBoard();
      syncFen();
    } catch (error) {
      showToast(error.message, true);
      syncFen();
    }
  });
  ["side", "castling", "en-passant", "halfmove", "fullmove"].forEach((id) => qs(id).addEventListener("input", syncFen));
  qs("confirm-history").addEventListener("change", (event) => {
    qs("analyze-button").disabled = !event.target.checked;
  });
  qs("analyze-button").addEventListener("click", analyze);
  qs("edit-position-button").addEventListener("click", () => {
    qs("result-section").classList.add("hidden");
    qs("analysis-setup").classList.remove("hidden");
  });
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
if (typeof module !== "undefined") module.exports = {
  expandPlacement,
  compressBoard,
  rotateBoard,
  analysisSummary,
  themeLabel,
  deltaLabel,
  noticeLabel,
};
