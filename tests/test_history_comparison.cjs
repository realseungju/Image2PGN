const test=require('node:test');const assert=require('node:assert/strict');
const comparison=require('../image2pgn/web/history-comparison.js');
test('global ply selection covers first, stepped, last and terminal position',()=>{
  const view={startPly:37,steps:[{}, {}, {}],game:{id:'game'}};
  assert.equal(comparison.selectedPly(view,0),37);assert.equal(comparison.selectedPly(view,1),37);
  assert.equal(comparison.selectedPly(view,2),38);assert.equal(comparison.selectedPly(view,3),39);
  assert.equal(comparison.selectedPly({...view,steps:[]},0),null);
  assert.equal(comparison.selectedPly(null,0),null);
});
test('late response rejected on step, game or session change',()=>{
  const view={startPly:37,steps:[{},{},{}],game:{id:'game'}};const request={jobId:'job',gameId:'game',ply:37};
  assert.ok(comparison.current(request,view,0,'job'));
  assert.ok(!comparison.current(request,view,2,'job'));
  assert.ok(!comparison.current(request,{...view,game:{id:'other'}},0,'job'));
  assert.ok(!comparison.current(request,view,0,'new-job'));
});
test('fixed white viewpoint and mate do not masquerade as centipawns',()=>{
  assert.equal(comparison.score({score_cp:-125,mate:null}),'흑 우세 · -1.25 (백 기준)');
  assert.equal(comparison.score({score_cp:null,mate:-3}),'흑 3수 내 메이트 예상');
  assert.equal(comparison.score({score_cp:null,mate:0}),'체크메이트');
  assert.equal(comparison.score({score_cp:0,mate:null}),'균형 · +0.00 (백 기준)');
});
