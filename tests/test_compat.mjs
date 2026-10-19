import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as sm4 from '../javascript/sm4.mjs';
const fixture=JSON.parse(readFileSync(new URL('./compat_vectors.json',import.meta.url),'utf8'));
for(const v of fixture.cases){
  const fn=sm4[`sm4_${v.operation}_${v.profile}_js`];
  const result=fn(v.data===null?null:[...Buffer.from(v.data,'hex')],v.key,v.iv,v.mode);
  assert.equal(result===null?null:Buffer.from(result).toString('hex'),v.expected,v.id);
}
console.log(`PASS JS DB adapters: ${fixture.cases.length} compatibility vectors`);
