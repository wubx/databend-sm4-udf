// Independent test oracle: Node/OpenSSL, never used by production implementations.
import {createCipheriv, createDecipheriv} from 'node:crypto';
import {writeFileSync} from 'node:fs';
const hex=b=>Buffer.from(b).toString('hex');
const k=Buffer.from('0123456789abcdeffedcba9876543210','hex');
const iv=Buffer.from('00112233445566778899aabbccddeeff','hex');
const cases=[];
function add(id,operation,data,key,v,mode,expected){
  cases.push({id,operation,data:data===null?null:hex(data),key:key===null?null:hex(key),iv:v===null?null:hex(v),mode,expected:expected===null?null:hex(expected)});
}
function oracle(data,mode,decrypt=false,padding=true){
  const c=(decrypt?createDecipheriv:createCipheriv)(`sm4-${mode}`,k,mode==='ecb'?null:iv);
  if(mode==='ecb'||mode==='cbc')c.setAutoPadding(padding);
  return Buffer.concat([c.update(data),c.final()]);
}
for(const mode of ['ecb','cbc','cfb','ofb']){
  const v=mode==='ecb'?Buffer.alloc(0):iv;
  for(const n of [0,1,12,15,16,17,31,32,33,64,128,255,256,1024,4096]){
    const data=Buffer.from(Array.from({length:n},(_,i)=>(i*73+n*19)&255));
    const ct=oracle(data,mode);
    add(`${mode}-${n}-enc`,'encrypt',data,k,v,mode,ct);
    add(`${mode}-${n}-dec`,'decrypt',ct,k,v,mode,data);
  }
  for(const text of ['text','中文🙂','hello\x01','hello\x02\x02','a\x00b']){
    const data=Buffer.from(text),ct=oracle(data,mode);
    add(`${mode}-utf8-${cases.length}`,'decrypt',ct,k,v,`SM4_128_${mode.toUpperCase()}`,data);
  }
}
// Regression: README's exact SQL must not silently return NULL for bare CBC.
// Keep a fixed expected ciphertext so regenerating fixtures cannot hide a regression.
const hello=Buffer.from('hello Databend','utf8');
const helloCipher=Buffer.from('4BCF1A8AEE7B4B3C742053F5EE965CBE','hex');
if(!oracle(hello,'cbc').equals(helloCipher))throw new Error('README regression/OpenSSL mismatch');
for(const mode of ['CBC','sm4-cbc','SM4_128_CBC']){
  add(`readme-hello-${mode}-enc`,'encrypt',hello,k,iv,mode,helloCipher);
  add(`readme-hello-${mode}-dec`,'decrypt',helloCipher,k,iv,mode,hello);
}
// Capitalized public-demo plaintext is intentionally distinct from the original regression.
const publicHello=Buffer.from('Hello Databend');
const publicCipher=Buffer.from('DA12F33F321D4D551A76D8800F5AE244','hex');
if(!oracle(publicHello,'cbc').equals(publicCipher))throw new Error('Public demo/OpenSSL mismatch');
for(const mode of ['CBC','sm4-cbc','SM4_128_CBC']){
  add(`public-hello-${mode}-enc`,'encrypt',publicHello,k,iv,mode,publicCipher);
  add(`public-hello-${mode}-dec`,'decrypt',publicCipher,k,iv,mode,publicHello);
}
// Published SM4 block KAT: first ECB ciphertext block must equal 681edf...4246.
add('standard-block-vector','encrypt',k,k,Buffer.alloc(0),'ECB',oracle(k,'ecb'));
// Normalize modes but do not trim or guess invalid names.
for(const mode of ['CBC','sm4-cbc','SM4_CBC','SM4_128_CBC','sm4-128-cbc']){
  add(`alias-${mode}`,'encrypt',Buffer.from('text'),k,iv,mode,oracle(Buffer.from('text'),'cbc'));
}
for(const mode of ['CFB','CFB128','sm4-cfb128','SM4_128_CFB128']){
  add(`alias-${mode}`,'encrypt',Buffer.from('text'),k,iv,mode,oracle(Buffer.from('text'),'cfb'));
}
for(const mode of ['', 'CBC ', ' cbc', 'SM4_128_CTR', 'GCM','SM4_SM4_CBC','cbc\n','ſM4_CBC']){
  for(const op of ['encrypt','decrypt'])add(`invalid-mode-${cases.length}`,op,k,k,iv,mode,null);
}
for(const op of ['encrypt','decrypt']){
  for(const n of [0,1,15,17,32])add(`bad-key-${op}-${n}`,op,k,Buffer.alloc(n),iv,'CBC',null);
  for(const n of [0,1,15,17,32])add(`bad-iv-${op}-${n}`,op,k,k,Buffer.alloc(n),'CBC',null);
  for(const field of ['data','key','iv','mode']){
    const args={data:k,key:k,iv,mode:'CBC'};args[field]=null;
    add(`null-${op}-${field}`,op,args.data,args.key,args.iv,args.mode,null);
  }
}
for(const n of [0,1,15,17,31])add(`bad-ct-size-${n}`,'decrypt',Buffer.alloc(n),k,iv,'CBC',null);
for(const p of [0,17,255]){
  const ct=oracle(Buffer.alloc(16,p),'cbc',false,false);
  add(`bad-padding-${p}`,'decrypt',ct,k,iv,'CBC',null);
}
const bad=Buffer.alloc(16,2);bad[14]=3;
add('bad-padding-mixed','decrypt',oracle(bad,'cbc',false,false),k,iv,'CBC',null);
// ECB ignores the contents/length of a non-NULL IV.
add('ecb-unused-iv','encrypt',k,k,Buffer.from('ignored'),'ECB',oracle(k,'ecb'));
// Fixed known examples with explicit caller-side key folding / IV normalization.
function folded(s){const out=Buffer.alloc(16);for(const [i,b] of Buffer.from(s).entries())out[i%16]^=b;return out;}
const dk=folded('F3229A0B371ED2D9441B830D21A390C3');
const defaultIV=Buffer.from('444f524953444f524953444f5249535f','hex');
const shortIV=Buffer.from(defaultIV);Buffer.from('0123456789').copy(shortIV);
const docs=[
  ['explicit_iv-ecb','asdasdasdasd',folded('12312313123'),Buffer.alloc(0),'ECB',Buffer.from('E0640595B963E365A70CB24DC8A3E349','hex')],
  ['explicit_iv-cbc','asdasdasdasd',folded('12312313123'),Buffer.from('asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj').subarray(0,16),'CBC',Buffer.from('646B83FDA4E969244E2B9BD835578D50','hex')],
  ['default_iv-ecb','text',dk,Buffer.alloc(0),'ECB',Buffer.from('aDjwRflBrDjhBZIOFNw3Tg==','base64')],
  ['default_iv-cbc-default','text',dk,defaultIV,'CBC',Buffer.from('FSYstvOmH2cXy7B/072Mug==','base64')],
  ['default_iv-cbc-short','text',dk,shortIV,'CBC',Buffer.from('1Y4NGIukSbv9OrkZnRD1bQ==','base64')],
];
for(const [id,text,key,v,mode,ct] of docs){
  add(id+'-enc','encrypt',Buffer.from(text),key,v,mode,ct);
  add(id+'-dec','decrypt',ct,key,v,mode,Buffer.from(text));
}
const fixture={schema:1,oracle:'Node.js crypto / OpenSSL SM4 plus five fixed known ciphertext examples',cases};
writeFileSync(new URL('./vectors.json',import.meta.url),JSON.stringify(fixture,null,2)+'\n');
console.log(`Generated ${cases.length} vectors`);
