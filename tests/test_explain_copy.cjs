const test=require('node:test');
const assert=require('node:assert/strict');
const {evaluation}=require('../image2pgn/web/explain-copy.js');
test('mate winner follows sign and fixed viewpoint',()=>{
  for(const [mate,view,winner] of [[1,'white','백'],[-2,'white','흑'],[3,'black','흑'],[-1,'black','백']]){
    assert.equal(evaluation({mate},view).label,`${winner}이 ${Math.abs(mate)}수 안에 체크메이트`);
  }
  assert.equal(evaluation({mate:0},'white').label,'체크메이트');
});
test('pawn scores use the same viewpoint and handle absent evaluations',()=>{
  assert.match(evaluation({mate:null,score_cp:-120},'black').label,/백이 유리/);
  assert.match(evaluation({mate:null,score_cp:120},'black').label,/흑이 유리/);
  assert.equal(evaluation({mate:null,score_cp:0},'white').label,'양쪽이 균형');
  assert.equal(evaluation({mate:null,score_cp:null},'white').label,'평가 정보 없음');
});
test('capture evaluation retains its later board context',()=>{
  const step={san:'Qg8+',to_square:'g8'};
  assert.equal(evaluation({mate:1,kind:'capture',steps:[step]},'white').context,'퀸을 g8로 옮긴 뒤의 평가');
  assert.equal(evaluation({mate:2,kind:'target',steps:[step]},'white').context,'분석을 시작한 판의 평가');
  assert.equal(evaluation({mate:-4,kind:'capture',comparison_stage:'current',steps:[{san:'Bxf6',to_square:'f6'}]},'black').context,'분석을 시작한 판의 평가');
  assert.equal(evaluation({mate:-4,kind:'capture',comparison_stage:'current'},'black').label,'백이 4수 안에 체크메이트');
});
