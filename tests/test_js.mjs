import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {sm4_encrypt_js,sm4_decrypt_js} from '../javascript/sm4.mjs';
const fixture=JSON.parse(readFileSync(new URL('./vectors.json',import.meta.url),'utf8'));
const bytes=s=>s===null?null:[...Buffer.from(s,'hex')];
for(const v of fixture.cases){
  const fn=v.operation==='encrypt'?sm4_encrypt_js:sm4_decrypt_js;
  const out=fn(bytes(v.data),bytes(v.key),bytes(v.iv),v.mode);
  assert.equal(out===null?null:Buffer.from(out).toString('hex'),v.expected,v.id);
}
assert.equal(Buffer.from(sm4_encrypt_js(bytes('0123456789abcdeffedcba9876543210'),bytes('0123456789abcdeffedcba9876543210'),[],'ECB')).toString('hex').slice(0,32),'681edf34d206965e86b3e94f536e4246');
console.log(`PASS JS: ${fixture.cases.length} shared vectors plus standard SM4 block KAT`);
