const test=require('node:test');
const assert=require('node:assert/strict');
const {select,positionLabel,resultText}=require('../image2pgn/web/history-replay.js');
const game={root_fen:'start w - - 0 1',match_plies:[1,3],steps:[
  {after_fen:'one b - - 0 1',uci:'e2e4'},
  {after_fen:'two w - - 0 2',uci:'e7e5'},
  {after_fen:'three b - - 1 2',uci:'g1f3'},
  {after_fen:'four w - - 2 3',uci:'b8c6'}
],result:'1-0'};
test('matched playback starts at chosen occurrence, full playback starts at root',()=>{
  const before=JSON.stringify(game);
  assert.deepEqual(select(game).steps.map(s=>s.uci),['e7e5','g1f3','b8c6']);
  assert.equal(select(game,false,3).root_fen,'three b - - 1 2');
  assert.equal(select(game,true,3).steps.length,4);
  assert.equal(select(game,true).root_fen,game.root_fen);
  assert.equal(JSON.stringify(game),before);
  assert.throws(()=>select(game,false,2));
});
test('final-position match has zero continuation and preserves recorded result',()=>{
  const end={...game,match_plies:[4]};
  assert.equal(select(end).steps.length,0);
  assert.equal(resultText(end.result),'백 승리');
  assert.equal(resultText('0-1'),'흑 승리');
  assert.equal(resultText('1/2-1/2'),'무승부');
});
test('move labels follow PGN side and move number',()=>{
  assert.equal(positionLabel(game,0),'1수 · 백 차례');
  assert.equal(positionLabel(game,1),'1수 · 흑 차례');
  assert.equal(positionLabel(game,3),'2수 · 흑 차례');
});
