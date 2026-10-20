/* Pure helpers shared by historical comparison UI and Node checks. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ChessLensComparison=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function selectedPly(view,index){if(!view||!view.steps.length)return null;return view.startPly+Math.max(0,Math.min(index-1,view.steps.length-1));}
  function score(value){
    if(value.mate!==null&&value.mate!==undefined)return value.mate===0?'체크메이트':(value.mate>0?'백':'흑')+' '+Math.abs(value.mate)+'수 내 메이트 예상';
    const cp=value.score_cp;if(cp===null||cp===undefined)return '평가 없음';
    return (cp===0?'균형':(cp>0?'백':'흑')+' 우세')+' · '+(cp>=0?'+':'')+(cp/100).toFixed(2)+' (백 기준)';
  }
  function current(request,view,index,jobId){return !!view&&request.jobId===jobId&&request.gameId===view.game.id&&request.ply===selectedPly(view,index);}
  return {selectedPly,score,current};
});
