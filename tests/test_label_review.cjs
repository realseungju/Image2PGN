// Pure JavaScript unit checks with a DOM stub, not a browser integration test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
const payload=html.match(/<script id="dataset" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script=html.match(/<\/script><script>([\s\S]*?)<\/script>/)[1];
const elements={}, storage={};
function el(id){return elements[id]??=( {value:'',checked:false,dataset:{},textContent:'',setAttribute(k,v){this[k]=v},replaceChildren(){},append(){},click(){}} )}
el('dataset').textContent=payload;el('filter').value='all';
const buttons=['white','black','unresolved'].map(side=>({dataset:{side},setAttribute(k,v){this[k]=v}}));
const context=vm.createContext({document:{getElementById:el,querySelectorAll:()=>buttons,createElement:()=>el('new')},localStorage:{getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v},Date,JSON,console,Blob,URL,setTimeout,confirm:()=>true});
vm.runInContext(script,context);
const run=s=>vm.runInContext(s,context);
assert.equal(run('items.length'),50);assert.equal(run('Object.keys(state.reviews).length'),0);
buttons[0].onclick();assert.equal(run('exported().reviews[items[0].id].status'),'proposed');assert.equal(run('exported().reviews[items[0].id].approved_for_training_or_benchmark'),false);
el('reviewer').value='unit-test';el('reviewer').onchange();el('evidence').value='test fixture source';el('evidence').onchange();el('verified').checked=true;el('verified').onchange();assert.equal(run('exported().reviews[items[0].id].approved_for_training_or_benchmark'),true);
assert.equal(run('Object.keys(validate(JSON.parse(JSON.stringify(exported()))).reviews).length'),1);
assert.throws(()=>run('validate({...state,manifest:"bad"})'));
assert.throws(()=>run('validate({...state,reviews:{bad:{}}})'));
assert.throws(()=>run('validate({...state,reviews:{[items[0].id]:{...state.reviews[items[0].id],sha256:"bad"}}})'));
buttons[2].onclick();assert.equal(run('exported().reviews[items[0].id].approved_for_training_or_benchmark'),false);
assert.equal(run('validate(JSON.parse(localStorage.getItem(key))).reviews[items[0].id].side'),'unresolved');
el('clear').onclick();assert.equal(run('Object.keys(state.reviews).length'),0);
console.log('PASS: 50 items; manual-only choices; evidence gate; export/import roundtrip; manifest, ID, image checksum rejection; pending exclusion; persistence; clear');
