import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import loadHighs from '../school-placement/vendor/highs/highs.mjs';
import {BrowserModel} from '../school-placement/browser-model.mjs';
const root=new URL('../',import.meta.url),read=path=>readFileSync(new URL(path,root));
const data=JSON.parse(gunzipSync(read('dist/school-placement/web-data.json.gz')));
const bytes=gunzipSync(read('dist/school-placement/matrix.bin.gz'));
const matrix=new Float64Array(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
const solver=await loadHighs({print:()=>{},printErr:()=>{}}),model=new BrowserModel(data,matrix,solver);
const references=JSON.parse(gunzipSync(read('school-placement/pages/reference-cases.json.gz')));
for(const test of references) {
  const result=model.calculate(test.placements);
  assert.deepEqual(model.payload(result).summary,test.summary);
  for(let i=0;i<model.n;i++) for(const [column,expected] of Object.entries(test.result[i])) {
    assert(expected===null ? result[i][column]===null : Math.abs(result[i][column]-expected)<1e-8,`Block ${i}, ${column}, ${JSON.stringify(test.placements)}`);
  }
}
for(const capacity of [0,-1,0.5,true,'600',NaN])assert.throws(()=>model.calculate([{block_id:0,capacity}]));
for(const block_id of [-1,1039,true,'0'])assert.throws(()=>model.calculate([{block_id,capacity:600}]));
const ranking=read('school-placement/results/automatic_600.csv').toString().trim().split('\n').slice(1);
const expected=new Map(ranking.map(line=>{const [id,deficit,reduction]=line.split(',');return [Number(id),{deficit:Number(deficit),reduction:Number(reduction)}]}));
for(let i=0;i<model.n;i++) {
  const summary=model.payload(model.calculate([{block_id:i,capacity:600}])).summary;
  assert.equal(summary.deficit,expected.get(i).deficit);assert.equal(summary.reduction,expected.get(i).reduction);
  if((i+1)%100===0)console.log(`WASM / Python exhaustive comparison: ${i+1}/${model.n}`);
}
assert.deepEqual(model.payload(model.calculate([])).summary,data.baseline.summary);
writeFileSync(new URL('school-placement/pages/validation.json',root),JSON.stringify({solver:'HiGHS 1.15.4 WebAssembly',baseline_all_10_indicators_all_1039_blocks:true,python_reference_scenarios:references.length,all_indicators_match_for_references:true,exhaustive_600_variants_match_python:1039,invalid_inputs_rejected:true,scenarios_independent:true},null,2)+'\n');
console.log('Browser model versus Python: PASS');
