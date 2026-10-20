/* Pure selection/copy helpers shared by the browser and Node regression checks. */
(function(root){
  'use strict';
  function positionLabel(game,ply){
    const fen=ply?game.steps[ply-1].after_fen:game.root_fen;
    const fields=fen.split(/\s+/);
    return fields[5]+'수 · '+(fields[1]==='w'?'백':'흑')+' 차례';
  }
  function select(game,fromStart=false,matchPly=game.match_plies[0]){
    if(!game.match_plies.includes(matchPly))throw Error('일치한 경기 시점이 아닙니다.');
    const ply=fromStart?0:matchPly;
    return {game,matchPly,startPly:ply,root_fen:ply?game.steps[ply-1].after_fen:game.root_fen,
      steps:game.steps.slice(ply),kind:'history'};
  }
  function resultText(result){
    return {'1-0':'백 승리','0-1':'흑 승리','1/2-1/2':'무승부'}[result]||'결과 미상';
  }
  const api={positionLabel,select,resultText};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.ChessLensHistory=api;
})(typeof window!=='undefined'?window:globalThis);
