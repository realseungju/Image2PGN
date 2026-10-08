/* ChessLens owns board editing, verified replay and popup sessions. */
"use strict";
const $ = id => document.getElementById(id);
let token='', job=null, poll=null, branchIndex=0, stepIndex=0, flipped=false, playing=false, animating=false, generation=0, renderedRevision=-1;
const params=new URLSearchParams(location.search);
let reviewFocus='*',reviewTurn='',capturePreviewGeneration=0,capturePreviewPending=false,capturePreviewValid=false;
function placement(fen){
  const cells=[]; const rows=fen.trim().split(/\s+/)[0].split('/');
  if(rows.length!==8) throw Error('FEN은 8개 행이어야 합니다.');
  for(const row of rows){let count=0;for(const p of row){if(/[1-8]/.test(p)){for(let i=0;i<Number(p);i++){cells.push('');count++;}}else if(/[prnbqkPRNBQK]/.test(p)){cells.push(p);count++;}else throw Error('FEN 기물 형식 오류');}if(count!==8)throw Error('FEN 행마다 8칸이어야 합니다.');}
  return cells;
}
function square(index){return 'abcdefgh'[index%8]+(8-Math.floor(index/8));}
function indexOf(s){return (8-Number(s[1]))*8+'abcdefgh'.indexOf(s[0]);}
function screenIndex(s){const i=indexOf(s);return flipped?63-i:i;}
function compress(cells){return Array.from({length:8},(_,r)=>{let row='',n=0;for(const p of cells.slice(r*8,r*8+8)){if(!p){n++;}else{if(n)row+=n;row+=p;n=0;}}if(n)row+=n;return row;}).join('/');}
function renderBoard(fen,editable=false){
  const cells=placement(fen);$('board').replaceChildren();
  for(let i=0;i<64;i++){const actual=flipped?63-i:i,p=cells[actual];const cell=document.createElement('button');cell.className='square'+((Math.floor(i/8)+i%8)%2?' dark':'');cell.dataset.square=square(actual);const focus=editable?reviewFocus:job?.result?.capture_comparison?.focus?.square;if(focus===square(actual))cell.classList.add('focus-piece');cell.title=square(actual)+(p?' '+p:'');cell.disabled=!editable;if(editable&&job?.recognition?.review_squares.some(s=>{const screen=s.screen_row*8+s.screen_col;return actual===(job.recognition.orientation==='black'?63-screen:screen);})){cell.classList.add('uncertain');cell.title+=' · 인식 확인 필요';}
    if(p){const piece=document.createElement('img');piece.src='/assets/pieces/'+(p===p.toUpperCase()?'w':'b')+p.toLowerCase()+'.svg';piece.alt=p;cell.append(piece);}
    const label=document.createElement('span');label.className='coord';label.textContent=square(actual);cell.append(label);
    if(editable)cell.onclick=()=>{if(!$('correction').open){if(p&&reviewTurn&&((p===p.toUpperCase())!==(reviewTurn==='w'))&&p.toLowerCase()!=='k'){reviewFocus=square(actual);resetConfirmation();refreshCaptures();}return;}try{const state=placement($('fen').value);state[actual]=$('piece').value;const fields=$('fen').value.trim().split(/\s+/);fields[0]=compress(state);$('fen').value=fields.join(' ');resetConfirmation();renderBoard($('fen').value,true);refreshCaptures();}catch(e){error(e);}};
    $('board').append(cell);
  }
}
function error(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{'x-chesslens-token':token,...(body&&!(body instanceof FormData)?{'Content-Type':'application/json'}:{})},body:body instanceof FormData?body:body?JSON.stringify(body):undefined});if(!response.ok){let text=await response.text();try{text=JSON.parse(text).detail;}catch{}throw Error(typeof text==='string'?text:JSON.stringify(text));}return response.json();}
function currentBranch(){return job?.result?.branches[branchIndex];}
function stopPlayback(){playing=false;$('play').textContent='재생';}
function drawArrow(step){const line=$('arrow');line.style.visibility=step?'visible':'hidden';if(!step)return;const a=screenIndex(step.from_square),b=screenIndex(step.to_square);line.setAttribute('x1',(a%8+.5)*100);line.setAttribute('y1',(Math.floor(a/8)+.5)*100);line.setAttribute('x2',(b%8+.5)*100);line.setAttribute('y2',(Math.floor(b/8)+.5)*100);}
function renderStep(){const branch=currentBranch();if(!branch)return;const step=branch.steps[stepIndex-1];renderBoard(step?step.after_fen:job.result.root_fen);drawArrow(step);$('counter').textContent=stepIndex+' / '+branch.steps.length;$('step').textContent=step?step.text_ko:'재생 또는 →를 눌러 다음 수를 보세요.';$('previous').disabled=stepIndex===0;$('next').disabled=stepIndex>=branch.steps.length;$('play').disabled=!branch.steps.length;$('move-list').replaceChildren();branch.steps.forEach((s,i)=>{const button=document.createElement('button');button.textContent=(i+1)+'. '+(s.short_ko||s.text_ko);button.className=i===stepIndex-1?'selected':'';button.onclick=()=>{if(animating)return;stopPlayback();stepIndex=i+1;renderStep();};$('move-list').append(button);});}
async function nextStep(){const branch=currentBranch();if(animating||!branch||stepIndex>=branch.steps.length)return;animating=true;const stamp=generation;const step=branch.steps[stepIndex];drawArrow(step);const box=$('board').getBoundingClientRect();const anims=[];for(const move of step.animation_moves||[step]){const from=document.querySelector('[data-square="'+move.from_square+'"] img');const a=screenIndex(move.from_square),b=screenIndex(move.to_square);if(from){from.style.zIndex='3';anims.push(from.animate([{transform:'translate(0,0)'},{transform:`translate(${(b%8-a%8)*box.width/8}px,${(Math.floor(b/8)-Math.floor(a/8))*box.height/8}px)`}],{duration:matchMedia('(prefers-reduced-motion:reduce)').matches?0:440,easing:'cubic-bezier(.2,.7,.2,1)',fill:'forwards'}).finished);}}await Promise.all(anims);if(stamp===generation){stepIndex++;renderStep();}animating=false;}
function showResult(){const r=job.result;branchIndex=0;stepIndex=0;$('result').hidden=false;$('review').hidden=true;$('board-section').hidden=false;$('brief').textContent=r.brief_ko;$('focus-result').textContent=r.capture_comparison?.focus?'설명 대상: '+r.capture_comparison.focus.label_ko:'';$('turn-result').textContent=(r.root_fen.split(/\s+/)[1]==='w'?'백':'흑')+' 차례로 분석했습니다.';const hasCapture=r.branches.some(b=>b.kind==='capture');$('branch').replaceChildren();r.branches.forEach((b,i)=>{const o=document.createElement('option');o.value=i;o.textContent=b.label_ko;$('branch').append(o);});if(r.capture_comparison?.focus&&hasCapture)$('branch').value=String(r.branches.findIndex(b=>b.kind==='capture'));changeBranch();if(!r.branches.length){renderBoard(r.root_fen);$('counter').textContent='0 / 0';$('step').textContent='게임이 끝났습니다.';$('play').disabled=true;$('next').disabled=true;$('previous').disabled=true;}}
function changeBranch(){stopPlayback();generation++;branchIndex=Number($('branch').value)||0;stepIndex=0;const b=currentBranch();if(!b){$('evaluation').textContent='종료';$('score-context').textContent='';$('capture-note').textContent=job.result.capture_comparison?.reason_ko||'이미 끝난 게임입니다.';return;}const copy=ChessLensCopy.evaluation(b,job.result.engine.viewpoint);$('brief').textContent=b.brief_ko||job.result.brief_ko;$('evaluation').textContent=copy.label;$('score-context').textContent=copy.context;$('capture-note').textContent=b.kind==='capture'?(job.result.capture_comparison?.reason_ko||'이 수로 잡는 경우를 가정한 수순입니다.'):(job.result.capture_comparison?.available?'위 목록에서 잡기 수순과 비교할 수 있습니다.':job.result.capture_comparison?.reason_ko||'이 분석에는 비교할 잡기 수순이 없습니다.');renderStep();}
function hasOverlays(){return (job?.recognition?.review_squares||[]).some(s=>s.reason==='colored_overlay');}
function resetConfirmation(){ $('confirm').checked=false;$('confirm-overlays').checked=false; }
function updateReviewGate(){
  $('analyse').disabled=job?.status!=='needs_input'||!reviewTurn||!reviewFocus||!$('confirm').checked||(hasOverlays()&&!$('confirm-overlays').checked)||capturePreviewPending||!capturePreviewValid;
}
function syncTurnButtons(){
  $('focus').disabled=!reviewTurn;
  $('turn-white').setAttribute('aria-pressed',String(reviewTurn==='w'));
  $('turn-black').setAttribute('aria-pressed',String(reviewTurn==='b'));
  $('turn-note').textContent=reviewTurn?(reviewTurn==='w'?'백':'흑')+'이 지금 둘 차례입니다.':'판 방향만으로 차례를 알 수 없습니다. 직접 선택해주세요.';
  updateReviewGate();
}
function chooseTurn(value){
  if(reviewTurn&&reviewTurn!==value)reviewFocus='*';
  reviewFocus=reviewFocus||'*';$('focus').value=reviewFocus;$('capture').value='';
  reviewTurn=value;
  const fields=$('fen').value.trim().split(/\s+/);fields[1]=value;$('fen').value=fields.join(' ');
  resetConfirmation();syncTurnButtons();refreshCaptures();
}
async function refreshCaptures(){
  const stamp=++capturePreviewGeneration;
  const id=job?.job_id;
  const select=$('capture');const saved=select.value;select.replaceChildren();
  const auto=document.createElement('option');auto.value='';auto.textContent='엔진이 선택';select.append(auto);select.disabled=true;
  capturePreviewValid=false;capturePreviewPending=false;
  if(!reviewTurn){$('capture-options-note').textContent='백 또는 흑 차례를 선택하면 잡을 수 있는 말을 보여줍니다.';updateReviewGate();return;}
  capturePreviewPending=true;updateReviewGate();$('capture-options-note').textContent='잡을 수 있는 말을 확인하고 있습니다.';
  try{
    const data=await api('/api/explanations/capture-options',{fen:$('fen').value.trim(),before_fen:$('before-fen').value.trim(),target_uci:$('target').value.trim(),focus_square:reviewFocus==='*'?'':reviewFocus});
    if(stamp!==capturePreviewGeneration||job?.job_id!==id||job?.status!=='needs_input')return;
    const focusSelect=$('focus');focusSelect.replaceChildren();
    const general=document.createElement('option');general.value='*';general.textContent='판 전체 분석';focusSelect.append(general);
    data.targets.forEach(t=>{const option=document.createElement('option');option.value=t.square;option.textContent=t.label_ko;focusSelect.append(option);});
    if(reviewFocus!=='*'&&!data.targets.some(t=>t.square===reviewFocus))reviewFocus='*';
    focusSelect.value=reviewFocus;
    $('focus-note').textContent=data.focus?'설명 대상: '+data.focus.label_ko+'. 이 말이 잡힌 뒤를 비교합니다.':reviewFocus==='*'?'판 전체의 최선 수를 분석합니다.':'목록에서 고르거나 체스판의 상대 기물을 누르세요.';
    if(!reviewFocus){$('capture-options-note').textContent='먼저 설명할 기물을 선택해주세요.';renderBoard($('fen').value,true);return;}
    renderBoard($('fen').value,true);
    data.captures.forEach(c=>{const option=document.createElement('option');option.value=c.uci;option.textContent=c.label_ko;select.append(option);});
    if(data.captures.some(c=>c.uci===saved))select.value=saved;
    select.disabled=!data.captures.length;
    $('capture-options-note').textContent=data.captures.length
      ? (data.turn==='white'?'백':'흑')+'이 '+(data.stage==='after_target'?'선택한 수 이후에 ':'지금 ')+'잡을 수 있는 수 '+data.captures.length+'개입니다. 비교할 잡기를 선택하거나 엔진에 맡기세요.'
      : data.reason_ko||'이 판과 차례에는 잡을 수 있는 말이 없습니다.';
    capturePreviewValid=true;
  }catch(e){if(stamp!==capturePreviewGeneration||job?.job_id!==id)return;$('capture-options-note').textContent='잡기를 확인할 수 없습니다. '+e.message;}
  finally{if(stamp===capturePreviewGeneration){capturePreviewPending=false;updateReviewGate();}}
}
function showReview(){
  const r=job.recognition;$('review').hidden=false;$('board-section').hidden=false;$('result').hidden=true;
  $('crop').hidden=!r?.board_image;if(r?.board_image)$('crop').src=r.board_image;
  $('recognition-note').textContent=r?'원본 화면은 '+(r.orientation==='black'?'흑':'백')+'이 아래에 있는 것으로 보입니다. '+(r.review_squares.length?'노란 칸 '+r.review_squares.length+'곳의 말을 확인하세요. ':'')+(r.board_details?.requires_review?'판의 테두리도 확인하세요. ':'')+'인식 오류는 판 인식 수정에서 고칠 수 있습니다.':job.recognition_error||'말의 위치와 차례를 확인하세요.';
  $('overlay-check').hidden=!hasOverlays();
  if(hasOverlays())$('recognition-note').textContent='화살표나 색 표시가 말 인식에 영향을 줄 수 있습니다. 노란 칸을 원본과 비교해주세요. '+$('recognition-note').textContent;
  $('fen').value=job.proposed_fen||(r?r.placement+' ? - - 0 1':'8/8/8/8/8/8/8/8 ? - - 0 1');
  reviewFocus=job.focus_square||'*';
  $('focus').replaceChildren();const defaultFocus=document.createElement('option');defaultFocus.value='*';defaultFocus.textContent='판 전체 분석';$('focus').append(defaultFocus);
  const side=$('fen').value.trim().split(/\s+/)[1];reviewTurn=['w','b'].includes(side)?side:'';
  $('before-fen').value=job.before_fen||'';$('target').value=job.target_uci||'';
  resetConfirmation();syncTurnButtons();renderBoard($('fen').value,true);refreshCaptures();
}
async function refresh(){if(!job)return;const id=job.job_id,stamp=generation;try{const latest=await api('/api/explanations/'+id);if(!job||id!==job.job_id||latest.revision<job.revision)return;job=latest;updateReviewGate();$('status').textContent=({queued:'분석 준비 중',recognizing:'체스판을 읽고 있습니다',needs_input:'판과 차례를 확인해주세요',analyzing:'이어질 수를 분석하고 있습니다',ready:'분석 완료',failed:'분석하지 못했습니다',cancelled:'분석이 닫혔습니다'}[job.status]||job.progress_stage)+(job.popup_error?' · '+job.popup_error:'');if(job.revision!==renderedRevision){renderedRevision=job.revision;if(job.status==='needs_input')showReview();if(job.status==='ready')showResult();if(job.status==='failed')error(Error(job.error));if(job.status==='cancelled'){stopPlayback();$('status').textContent='닫힌 분석입니다.';$('review').hidden=true;if(window.chesslensShell)window.chesslensShell.close();}}}catch(e){error(e);}}
async function start(){try{$('error').hidden=true;const form=new FormData();form.set('request_id',crypto.randomUUID());form.set('question',$('question').value);const image=$('image').files[0];if(image)form.set('image',image);if($('initial-fen').value.trim()){form.set('fen',$('initial-fen').value.trim());form.set('confirmed_history',String($('initial-confirm').checked));}await attach(await api('/api/explanations',form));}catch(e){error(e);}}
async function attach(value){stopPlayback();generation++;job=value;renderedRevision=-1;$('start').hidden=true;if(poll)clearInterval(poll);await refresh();poll=setInterval(refresh,700);}
async function closeSession(){stopPlayback();generation++;if(poll)clearInterval(poll);if(job){try{await api('/api/explanations/'+job.job_id+'/cancel',{});}catch(e){error(e);}}if(window.chesslensShell)window.chesslensShell.close();else{$('status').textContent='분석이 닫혔습니다.';$('start').hidden=false;$('review').hidden=true;$('result').hidden=true;$('board-section').hidden=true;job=null;}}
async function init(){try{token=(await api('/api/explanations/session')).token;const id=params.get('job');if(id)await attach(await api('/api/explanations/'+id));const handoff=sessionStorage.getItem('chesslens-confirmed-fen');if(handoff&&!id){sessionStorage.removeItem('chesslens-confirmed-fen');$('initial-fen').value=handoff;$('initial-confirm').checked=true;}}catch(e){error(e);}if(params.get('shell')==='1'&&window.chesslensShell)document.body.classList.add('shell');}
$('submit').onclick=start;$('close').onclick=closeSession;$('new').onclick=closeSession;$('branch').onchange=changeBranch;$('previous').onclick=()=>{if(animating)return;stopPlayback();stepIndex=Math.max(0,stepIndex-1);renderStep();};$('next').onclick=()=>{stopPlayback();nextStep();};$('flip').onclick=()=>{if(animating)return;stopPlayback();flipped=!flipped;if(job?.status==='needs_input')renderBoard($('fen').value,true);else if(job?.result&&!job.result.branches.length)renderBoard(job.result.root_fen);else renderStep();};$('fen').onchange=()=>{try{resetConfirmation();const side=$('fen').value.trim().split(/\s+/)[1];reviewTurn=['w','b'].includes(side)?side:'';syncTurnButtons();renderBoard($('fen').value,true);refreshCaptures();}catch(e){error(e);}};
$('turn-white').onclick=()=>chooseTurn('w');$('turn-black').onclick=()=>chooseTurn('b');
$('confirm').onchange=updateReviewGate;$('confirm-overlays').onchange=updateReviewGate;
$('focus').onchange=()=>{reviewFocus=$('focus').value;$('capture').value='';resetConfirmation();refreshCaptures();};
$('refocus').onclick=async()=>{try{const form=new FormData();form.set('request_id',crypto.randomUUID());form.set('question',job.question||'이 기물을 잡으면 어떻게 되나요?');form.set('fen',job.result.fen);form.set('before_fen',job.before_fen||'');form.set('target_uci',job.target_uci||'');await attach(await api('/api/explanations',form));}catch(e){error(e);}};
for(const id of ['before-fen','target'])$(id).onchange=()=>{resetConfirmation();refreshCaptures();};
$('capture').onchange=()=>{resetConfirmation();updateReviewGate();};


$('play').onclick=async()=>{if(playing){stopPlayback();return;}const b=currentBranch();if(!b)return;if(stepIndex>=b.steps.length){stepIndex=0;renderStep();}playing=true;$('play').textContent='멈춤';const stamp=generation;while(playing&&stamp===generation&&stepIndex<b.steps.length){await nextStep();await new Promise(r=>setTimeout(r,1050));}if(stamp===generation)stopPlayback();};
$('analyse').onclick=async()=>{try{$('error').hidden=true;if(!reviewTurn||!reviewFocus||capturePreviewPending||!capturePreviewValid)throw Error('차례를 선택하고 잡기 확인이 끝난 뒤 분석해주세요.');$('analyse').disabled=true;await api('/api/explanations/'+job.job_id+'/answers',{revision:job.revision,question_id:'confirm-position',fen:$('fen').value.trim(),confirmed_history:$('confirm').checked,confirmed_overlays:$('confirm-overlays').checked,before_fen:$('before-fen').value.trim(),target_uci:$('target').value.trim(),capture_uci:$('capture').value,focus_square:reviewFocus==='*'?'':reviewFocus});await refresh();}catch(e){error(e);updateReviewGate();}};
window.addEventListener('pagehide',()=>{stopPlayback();if(poll)clearInterval(poll);});init();
