/* A draft only participates in matching after the user reviews and applies it. */
function createSceneSearch(){
  let frames=null;
  let draft=null;
  let revision=0;
  const endpoint=()=>'/api/explanations/'+job.job_id+'/scenes';
  const fens=()=>frames.map(frame=>frame.fen);
  const statusLabels={
    available:'조회 완료', partial:'일부 확인', busy:'조회 중', unavailable:'연결 실패',
    rate_limited:'요청 제한', auth_required:'인증 필요', not_requested:'미조회'
  };
  function invalidate(){
    revision++;
    historySearchGeneration++;
    if(historyView)changeBranch();
    $('history-games').replaceChildren();
    $('history-caveat').textContent='';
    $('history-status').textContent='';
    $('history-policy').textContent='';
  }
  function reset(){
    revision++;
    frames=null;
    draft=null;
    $('scenes').hidden=true;
    $('scenes-open').hidden=false;
    $('scene-editor').hidden=true;
    $('scene-preview').removeAttribute('src');
    $('scene-list').replaceChildren();
  }
  function renderList(){
    const list=$('scene-list');
    list.replaceChildren();
    frames.forEach((frame,index)=>{
      const row=document.createElement('li');
      row.append(document.createTextNode(frame.name+' '));
      const addButton=(label,action,disabled=false)=>{
        const button=document.createElement('button');
        button.textContent=label;
        button.disabled=disabled || draft!==null;
        button.onclick=action;
        row.append(button);
      };
      addButton('수정',()=>edit(index));
      addButton('위로',()=>move(index,-1),index===0);
      addButton('아래로',()=>move(index,1),index===frames.length-1);
      addButton('삭제',()=>{frames.splice(index,1);search();});
      addButton('이 장면으로 Masters 조회',()=>search(index));
      list.append(row);
    });
    $('scene-add').disabled=draft!==null || frames.length>=16;
    $('scene-add').textContent=frames.length>=16?'장면 최대 16개':'장면 추가';
    $('history-retry').disabled=draft!==null || frames.length===0;
  }
  function move(index,offset){
    const other=index+offset;
    [frames[other],frames[index]]=[frames[index],frames[other]];
    search();
  }
  async function search(remoteFrame=null){
    if(!frames || draft)return;
    invalidate();
    renderList();
    if(!frames.length){
      $('history-status').textContent='검색할 장면을 추가하세요.';
      return;
    }
    const stamp=revision;
    const positions=fens();
    $('history-status').textContent='장면 순서를 대조하고 있습니다.';
    try{
      const data=await api(endpoint(),{frames:positions,remote_frame:remoteFrame});
      if(stamp!==revision)return;
      const scope=data.remote_statuses.map((s,i)=>(i+1)+'번 '+(statusLabels[s]||s)).join(' · ');
      const count=data.games.length;
      const message=count?'현재 검색 범위에서 '+count+'경기 일치':
        data.first_unmatched+'번째 장면부터 순서가 맞는 경기가 없습니다.';
      renderMasterGames({...data,policy_ko:'내장 '+data.catalog_size+'경기 · Masters '+scope,
        message_ko:message,caveat_ko:'외부 조회는 선택한 장면의 상위 15개 후보 중 최대 3개 원기보를 확인합니다.'},positions);
    }catch(e){if(stamp===revision)$('history-status').textContent=e.message;}
  }
  for(const option of $('piece').options){
    $('scene-piece').append(option.cloneNode(true));
  }
  function drawDraft(){
    const board=$('scene-board');
    board.replaceChildren();
    let cells;
    try{cells=placement($('scene-fen').value);}catch{return;}
    for(const [index,piece] of cells.entries()){
      const cell=document.createElement('button');
      cell.className='square'+((Math.floor(index/8)+index%8)%2?' dark':'');
      if(draft?.marks?.includes(index))cell.classList.add('uncertain');
      cell.setAttribute('aria-label',square(index)+' '+(piece||'빈칸'));
      if(piece){
        const icon=document.createElement('img');
        icon.src='/assets/pieces/'+(piece===piece.toUpperCase()?'w':'b')+piece.toLowerCase()+'.svg';
        icon.alt=piece;
        cell.append(icon);
      }
      cell.onclick=()=>{
        const fields=$('scene-fen').value.trim().split(/\s+/);
        cells[index]=$('scene-piece').value;
        fields[0]=compress(cells);
        $('scene-fen').value=fields.join(' ');
        $('scene-fen').oninput();
      };
      board.append(cell);
    }
  }
  function edit(index){
    invalidate();
    const original=frames[index];
    draft={index,name:original?.name||'직접 입력',image:original?.image||'',marks:original?.marks||[]};
    $('scene-job').value='';
    $('scene-file').value='';
    $('scene-fen').value=original?.fen||'';
    $('scene-side').value=original?.fen.split(/\s+/)[1]||'?';
    drawDraft();
    $('scene-feedback').textContent='';
    $('scene-preview').hidden=!draft.image;
    if(draft.image)$('scene-preview').src=draft.image;
    $('scene-editor').hidden=false;
    $('scene-confirm').disabled=false;
    renderList();
  }
  function closeEditor(){
    draft=null;
    $('scene-editor').hidden=true;
    $('scene-preview').removeAttribute('src');
    search();
  }
  $('scenes-open').onclick=()=>{
    frames=[{fen:job.result.fen,name:'처음 확인한 판',image:job.recognition?.board_image||''}];
    $('scenes').hidden=false;
    $('scenes-open').hidden=true;
    edit(1);
  };
  $('scenes-close').onclick=()=>{invalidate();reset();loadMasterGames();};
  $('scene-add').onclick=()=>edit(frames.length);
  $('scene-abandon').onclick=closeEditor;
  $('scene-side').onchange=()=>{
    const parts=$('scene-fen').value.trim().split(/\s+/);
    if(parts.length===6){parts[1]=$('scene-side').value;$('scene-fen').value=parts.join(' ');$('scene-fen').oninput();}
  };
  $('scene-fen').oninput=()=>{
    revision++;
    $('scene-confirm').disabled=false;
    drawDraft();
    const side=$('scene-fen').value.trim().split(/\s+/)[1];
    $('scene-side').value=['w','b'].includes(side)?side:'?';
  };
  $('scene-file').onchange=async()=>{
    const file=$('scene-file').files[0];
    if(!file || !draft)return;
    const stamp=++revision;
    $('scene-confirm').disabled=true;
    $('scene-fen').value='';
    drawDraft();
    $('scene-side').value='?';
    $('scene-preview').hidden=true;
    draft.image='';
    draft.marks=[];
    draft.name=file.name;
    $('scene-feedback').textContent='체스판을 읽고 있습니다.';
    try{
      const body=new FormData();
      body.set('image',file);
      const result=await api('/api/explanations/'+job.job_id+'/scene-image',body);
      if(stamp!==revision)return;
      draft.marks=result.review_squares.map(square=>{
        const index=square.screen_row*8+square.screen_col;
        return result.orientation==='black'?63-index:index;
      });
      draft.image=result.board_image;
      $('scene-preview').src=draft.image;
      $('scene-preview').hidden=false;
      $('scene-fen').value=result.placement+' ? - - 0 1';
      drawDraft();
      $('scene-feedback').textContent='인식 결과를 확인하세요. 검토 표시 '+result.review_squares.length+'칸.';
    }catch(e){if(stamp===revision)$('scene-feedback').textContent=e.message;}
    finally{if(stamp===revision)$('scene-confirm').disabled=false;}
  };
  $('scene-import').onclick=async()=>{
    const raw=$('scene-job').value.trim();
    let id=raw;
    try{id=new URL(raw).searchParams.get('job');}catch{}
    if(!/^[a-f0-9]{32}$/.test(id||'')){
      $('scene-feedback').textContent='이 서비스에서 연 분석 링크 또는 작업 ID를 입력하세요.';
      return;
    }
    const stamp=++revision;
    $('scene-confirm').disabled=true;
    try{
      const saved=await api('/api/explanations/'+id);
      if(stamp!==revision)return;
      if(saved.status!=='ready')throw Error('해당 분석에서 먼저 판 확인을 마치세요.');
      draft.name='확인한 분석';
      draft.image=saved.recognition?.board_image||'';
      draft.marks=[];
      $('scene-preview').hidden=!draft.image;
      if(draft.image)$('scene-preview').src=draft.image;
      $('scene-fen').value=saved.result.fen;
      $('scene-side').value=saved.result.fen.split(/\s+/)[1];
      drawDraft();
      $('scene-feedback').textContent='확인한 판을 가져왔습니다.';
    }catch(e){if(stamp===revision)$('scene-feedback').textContent=e.message;}
    finally{if(stamp===revision)$('scene-confirm').disabled=false;}
  };
  $('scene-confirm').onclick=async()=>{
    if(!draft)return;
    const fen=$('scene-fen').value.trim();
    if(fen.split(/\s+/).length!==6 || $('scene-side').value==='?'){
      $('scene-feedback').textContent='전체 FEN과 둘 차례를 확인하세요.';
      return;
    }
    const stamp=++revision;
    $('scene-confirm').disabled=true;
    try{
      // Check the reviewed position before replacing a previously valid frame.
      await api(endpoint(),{frames:[fen]});
      if(stamp!==revision)return;
      frames[draft.index]={fen,name:draft.name,image:draft.image,marks:draft.marks};
      closeEditor();
    }catch(e){if(stamp===revision)$('scene-feedback').textContent=e.message;}
    finally{if(stamp===revision)$('scene-confirm').disabled=false;}
  };
  return {get active(){return frames!==null;},fens,search,reset};
}
