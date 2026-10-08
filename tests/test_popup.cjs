const {test}=require('node:test');
const assert=require('node:assert/strict');
const {popupBounds}=require('../desktop/window-placement.cjs');
test('primary placement stays inside work area',()=>{
  const area={x:0,y:0,width:1920,height:1032};
  assert.deepEqual(popupBounds(area,null),{x:1416,y:32,width:480,height:850});
});
test('negative monitor and edge hint clamp correctly',()=>{
  const area={x:-1920,y:0,width:1920,height:1032};
  const bounds=popupBounds(area,{x:-100,y:1000,width:900,height:200});
  assert.equal(bounds.x,-480);assert.equal(bounds.y,182);
});
test('DIP work area and small displays constrain size',()=>{
  assert.deepEqual(popupBounds({x:-1280,y:-100,width:1280,height:680},{x:-1200,y:-200,width:500,height:300}),{x:-1196,y:-100,width:480,height:680});
  assert.deepEqual(popupBounds({x:0,y:0,width:400,height:350},null),{x:0,y:0,width:400,height:350});
});
