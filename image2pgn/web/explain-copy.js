/* Presentation only: score sign is relative to the engine's fixed viewpoint. */
(function(root){
  "use strict";
  function evaluation(branch, viewpoint){
    const own=viewpoint==='white'?'백':'흑', other=own==='백'?'흑':'백';
    let label;
    if(branch.mate!==null && branch.mate!==undefined){
      label=branch.mate===0?'체크메이트':(branch.mate>0?own:other)+'이 '+Math.abs(branch.mate)+'수 안에 체크메이트';
    }else if(Number.isFinite(branch.score_cp)){
      label=branch.score_cp===0?'양쪽이 균형':(branch.score_cp>0?own:other)+'이 유리 · '+(Math.abs(branch.score_cp)/100).toFixed(2);
    }else{label='평가 정보 없음';}
    const first=branch.steps?.[0];
    const piece={P:'폰',N:'나이트',B:'비숍',R:'룩',Q:'퀸',K:'킹'}[(first?.san||'').replace(/^[a-h]/,'P')[0]];
    const stage=branch.kind==='capture'&&branch.comparison_stage!=='current'&&first
      ? (piece?piece+(piece==='나이트'?'를 ':'을 '): '')+first.to_square+'로 옮긴 뒤의 평가'
      : '분석을 시작한 판의 평가';
    return {label,context:stage};
  }
  const api={evaluation};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.ChessLensCopy=api;
})(globalThis);
