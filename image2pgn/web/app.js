const PIECES = [".","K","Q","R","B","N","P","k","q","r","b","n","p"];
const SYMBOLS = {".":"×",K:"♔",Q:"♕",R:"♖",B:"♗",N:"♘",P:"♙",k:"♚",q:"♛",r:"♜",b:"♝",n:"♞",p:"♟"};
const THEME_LABELS = {
  "wins or trades material":"기물을 잡거나 교환합니다", "forces check":"체크를 강제합니다",
  "improves king safety":"킹 안전을 높입니다", "develops a minor piece":"경기물을 전개합니다",
  "fights for the center":"중앙을 장악합니다", "opens lines with a pawn break":"폰 돌파로 길을 엽니다",
  "increases heavy-piece activity":"룩·퀸의 활동성을 높입니다", "adds pressure near the enemy king":"상대 킹 주변을 압박합니다",
  "creates a fork threat":"포크 위협을 만듭니다", "creates or increases a pin":"핀을 만들거나 강화합니다",
  "threatens checkmate next move":"다음 수 체크메이트를 위협합니다"
};
let board = Array.from({length:8},()=>Array(8).fill("."));
let selectedPiece = ".";
let sourceFile = null;

function expandPlacement(placement){
  const ranks=placement.trim().split("/");
  if(ranks.length!==8) throw new Error("FEN은 8개 행이어야 합니다.");
  return ranks.map(rank=>{const row=[];for(const char of rank){if(/[1-8]/.test(char))row.push(...Array(Number(char)).fill("."));else if(/[prnbqkPRNBQK]/.test(char))row.push(char);else throw new Error("허용되지 않은 FEN 문자입니다.");}if(row.length!==8)throw new Error("각 FEN 행은 8칸이어야 합니다.");return row;});
}
function compressBoard(value){return value.map(row=>{let out="",empty=0;for(const piece of row){if(piece==="."){empty++;continue}if(empty){out+=empty;empty=0}out+=piece}return out+(empty||"")}).join("/")}
function rotateBoard(value){return value.slice().reverse().map(row=>row.slice().reverse())}
function qs(id){return document.getElementById(id)}
function showToast(message,error=false){const toast=qs("toast");toast.textContent=message;toast.className="toast"+(error?" error":"");setTimeout(()=>toast.classList.add("hidden"),4500)}
function formatBytes(bytes){return bytes<1048576?`${(bytes/1024).toFixed(1)} KiB`:`${(bytes/1048576).toFixed(1)} MiB`}
function fullFen(){return `${compressBoard(board)} ${qs("side").value} ${qs("castling").value.trim()||"-"} ${qs("en-passant").value.trim()||"-"} ${qs("halfmove").value||0} ${qs("fullmove").value||1}`}
function syncFen(){qs("placement").value=compressBoard(board);qs("full-fen").textContent=fullFen()}
function analysisSummary(result){const best=result.moves?.[0];if(!best)return result.evaluation==="game over"?"이미 종료된 포지션입니다.":"Stockfish가 후보 수를 반환하지 않았습니다.";if(best.mate!==null&&best.mate!==undefined)return best.mate>0?`강제 체크메이트가 있습니다. 첫 수는 ${best.san}입니다.`:`위험한 포지션입니다. 최선의 방어는 ${best.san}이지만 체크메이트 위협이 남습니다.`;if(best.score_cp===null||best.score_cp===undefined)return `Stockfish 최우선 후보는 ${best.san}입니다.`;const cp=best.score_cp;const status=cp>=150?"뚜렷하게 유리합니다":cp>=50?"조금 유리합니다":cp>-50?"대체로 균형입니다":cp>-150?"조금 불리합니다":"매우 위험합니다";return `Stockfish 최우선 후보는 ${best.san}입니다. 현재 차례 쪽 기준으로 ${status}.`}
function themeLabel(theme){return THEME_LABELS[theme]||theme}
function deltaLabel(delta){if(delta==="best-eval")return "최선";const match=/^([+-]\d+\.\d+) vs best$/.exec(delta);return match?`최선 대비 ${match[1]}`:delta}
function noticeLabel(value){return value.replace(/^Hanging piece: ([KQRBNP]) on ([a-h][1-8]) is attacked and undefended\.$/,"방어되지 않은 $1 기물이 $2에서 공격받고 있습니다.").replace(/^Immediate mate threat: opponent can play (.+)\.$/,"상대의 즉시 체크메이트 위협: $1").replace(/^Forcing checks available to opponent: (.+)\.$/,"상대가 둘 수 있는 강제 체크: $1").replace(/^Forcing captures available to opponent: (.+)\.$/,"상대가 둘 수 있는 강제 캡처: $1").replace("The FEN is not fully valid according to python-chess.","python-chess 기준으로 완전히 유효한 FEN이 아닙니다.").replace("Castling rights are present; verify them if the FEN came from a single screenshot.","스크린샷만으로는 캐슬링 권리를 알 수 없습니다. 입력값을 확인하세요.").replace("En-passant square is present; verify it if the FEN came from a single screenshot.","스크린샷만으로는 앙파상 칸을 알 수 없습니다. 입력값을 확인하세요.")}

function renderBoard(){
  const root=qs("chessboard");root.innerHTML="";
  board.forEach((row,r)=>row.forEach((piece,c)=>{const square=document.createElement("button");square.type="button";square.className=`square ${(r+c)%2?"dark":"light"}`;square.textContent=SYMBOLS[piece]||"";square.setAttribute("aria-label",`${String.fromCharCode(97+c)}${8-r} ${piece}`);square.addEventListener("click",()=>{board[r][c]=selectedPiece;renderBoard();syncFen()});root.append(square)}));
}
function renderPalette(){const root=qs("piece-palette");root.innerHTML="";PIECES.forEach(piece=>{const button=document.createElement("button");button.type="button";button.className="piece-choice"+(piece===selectedPiece?" selected":"");button.textContent=SYMBOLS[piece];button.title=piece==="."?"빈칸":piece;button.addEventListener("click",()=>{selectedPiece=piece;renderPalette()});root.append(button)})}
function setFile(file){if(!file)return;sourceFile=file;qs("source-preview").src=URL.createObjectURL(file);qs("file-name").textContent=file.name;qs("file-size").textContent=formatBytes(file.size);qs("upload-preview").classList.remove("hidden")}

async function recognize(){
  if(!sourceFile)return showToast("이미지를 먼저 선택하세요.",true);
  document.body.classList.add("loading");qs("recognize-button").textContent="인식 중…";
  try{const data=new FormData();data.append("image",sourceFile);const response=await fetch("/api/recognize",{method:"POST",body:data});const result=await response.json();if(!response.ok)throw new Error(result.detail||"인식 실패");
    board=expandPlacement(result.placement);renderBoard();syncFen();qs("normalized-board").src=result.board_image;
    const details=result.board_details||{};qs("detection-copy").textContent=`검출: ${details.method||"unknown"} · 경계: ${(details.bounds||[]).join(", ")||"별도 확인"}`;
    const badges=qs("recognition-badges");badges.innerHTML="";[[`방향 ${result.orientation}`,result.orientation_status==="uncertain"],[`검출 ${details.method||"unknown"}`,!!details.requires_review],[`검토 칸 ${(result.review_squares||[]).length}`,result.review_squares?.length>0]].forEach(([label,warn])=>{const span=document.createElement("span");span.className="badge"+(warn?" warn":"");span.textContent=label;badges.append(span)});
    const warnings=[];if(details.requires_review)warnings.push("자동 경계가 확인되지 않았습니다. 분석 전에 원본과 정규화 보드를 비교하세요.");if(result.orientation_status==="uncertain")warnings.push("방향 근거가 부족합니다. 필요하면 보드를 180° 뒤집으세요.");if(result.review_squares?.length)warnings.push(`낮은 신뢰도의 말 ${result.review_squares.length}칸을 직접 확인하세요.`);const warning=qs("recognition-warning");warning.textContent=warnings.join(" ");warning.classList.toggle("hidden",!warnings.length);
    qs("review-section").classList.remove("hidden");qs("review-section").scrollIntoView({behavior:"smooth"});
  }catch(error){showToast(error.message,true)}finally{document.body.classList.remove("loading");qs("recognize-button").textContent="보드 인식하기"}
}

function renderAnalysis(result){qs("evaluation").textContent=result.evaluation;qs("summary").textContent=analysisSummary(result);const moves=qs("candidate-moves");moves.innerHTML="";(result.moves||[]).forEach(move=>{const card=document.createElement("div");card.className="move-card";card.innerHTML=`<span class="move-rank">${move.rank}</span><div class="move-main"><strong>${move.san}</strong><p>PV · ${move.pv_san.slice(0,6).join(" ")||"—"}</p><p>${move.themes.map(themeLabel).join(" · ")||"전반적인 포지션 개선"}</p></div><span class="move-score">${move.score}<br><small>${deltaLabel(move.delta)}</small></span>`;moves.append(card)});if(!result.moves?.length)moves.innerHTML='<p class="empty-state">후보 수가 없습니다.</p>';
  const notices=qs("threats");notices.innerHTML="";[...(result.warnings||[]),...(result.threats||[])].forEach(text=>{const div=document.createElement("div");div.className="notice";div.textContent=noticeLabel(text);notices.append(div)});if(!notices.children.length)notices.innerHTML='<p class="empty-state">표시할 즉시 위협이 없습니다.</p>';qs("result-section").classList.remove("hidden");qs("result-section").scrollIntoView({behavior:"smooth"})}
async function analyze(){document.body.classList.add("loading");qs("analyze-button").innerHTML="분석 중… <span>⌛</span>";try{const response=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fen:fullFen(),confirmed_history:qs("confirm-history").checked,top:3,depth:14})});const result=await response.json();if(!response.ok)throw new Error(result.detail||"분석 실패");renderAnalysis(result)}catch(error){showToast(error.message,true)}finally{document.body.classList.remove("loading");qs("analyze-button").innerHTML="Stockfish 분석 시작 <span>→</span>"}}

function init(){renderPalette();renderBoard();syncFen();const input=qs("image-input"),drop=qs("dropzone");input.addEventListener("change",()=>setFile(input.files[0]));["dragenter","dragover"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.add("drag")}));["dragleave","drop"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.remove("drag")}));drop.addEventListener("drop",event=>setFile(event.dataTransfer.files[0]));qs("recognize-button").addEventListener("click",recognize);qs("flip-button").addEventListener("click",()=>{board=rotateBoard(board);renderBoard();syncFen()});qs("placement").addEventListener("change",event=>{try{board=expandPlacement(event.target.value);renderBoard();syncFen()}catch(error){showToast(error.message,true);syncFen()}});["side","castling","en-passant","halfmove","fullmove"].forEach(id=>qs(id).addEventListener("input",syncFen));qs("confirm-history").addEventListener("change",event=>{qs("analyze-button").disabled=!event.target.checked});qs("analyze-button").addEventListener("click",analyze)}
if(typeof document!=="undefined")document.addEventListener("DOMContentLoaded",init);
if(typeof module!=="undefined")module.exports={expandPlacement,compressBoard,rotateBoard,analysisSummary,themeLabel,deltaLabel,noticeLabel};
