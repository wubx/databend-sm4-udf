// Independent OpenSSL oracle for string-key normalization; no project imports.
import {createCipheriv} from 'node:crypto';
import {writeFileSync} from 'node:fs';
const cases=[];
const utf8=s=>Buffer.from(s,'utf8');
const DEFAULT_IV=Buffer.from('444f524953444f524953444f5249535f','hex');
function folded(s){const key=Buffer.alloc(16);for(const [i,b] of utf8(s).entries())key[i%16]^=b;return key;}
function vector(s,profile){
  const raw=utf8(s),out=profile==='default_iv'?Buffer.from(DEFAULT_IV):Buffer.alloc(16);
  raw.copy(out,0,0,16);return out;
}
function encrypt(data,key,iv,mode,profile,padding=true){
  const c=createCipheriv('sm4-'+mode,folded(key),mode==='ecb'?null:vector(iv,profile));
  if(mode==='ecb'||mode==='cbc')c.setAutoPadding(padding);
  return Buffer.concat([c.update(data),c.final()]);
}
function add(id,profile,operation,data,key,iv,mode,expected){
  cases.push({id,profile,operation,data:data===null?null:data.toString('hex'),key,iv,mode,
    expected:expected===null?null:expected.toString('hex')});
}
const defaultKey='F3229A0B371ED2D9441B830D21A390C3',explicitKey='12312313123';
const longIV='asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj';
const known=[
  ['explicit_iv-ecb','explicit_iv','asdasdasdasd',explicitKey,'','sm4-ecb','E0640595B963E365A70CB24DC8A3E349','hex'],
  ['explicit_iv-cbc','explicit_iv','asdasdasdasd',explicitKey,longIV,'sm4-cbc','646B83FDA4E969244E2B9BD835578D50','hex'],
  ['default_iv-ecb','default_iv','text',defaultKey,'','SM4_128_ECB','aDjwRflBrDjhBZIOFNw3Tg==','base64'],
  ['default_iv-cbc-default','default_iv','text',defaultKey,'','SM4_128_CBC','FSYstvOmH2cXy7B/072Mug==','base64'],
  ['default_iv-cbc-short','default_iv','text',defaultKey,'0123456789','SM4_128_CBC','1Y4NGIukSbv9OrkZnRD1bQ==','base64'],
];
for(const [id,profile,text,key,iv,mode,ct,encoding] of known){
  const cipher=Buffer.from(ct,encoding);
  add(id+'-enc',profile,'encrypt',utf8(text),key,iv,mode,cipher);
  add(id+'-dec',profile,'decrypt',cipher,key,iv,mode,utf8(text));
}
// Public-demo regressions: preserve independent, fixed expectations after changing case/text.
const hello=utf8('Hello Databend');
const helloHex=['742FDCD4D976A043AC7F7F451B62B50F','80ECC1CD2C248143DC470A7D5318EF15',
  '5E21ED5A0C3897EFC275E888B1605F7D','08885AE98D505F1D421D63B055AFA26A','AC463EB599C6F7C6ABFC2196293C24D9'];
for(const [index,[id,profile,,key,iv,mode]] of known.entries()){
  const expected=Buffer.from(helloHex[index],'hex');
  const cipherMode=mode.toLowerCase().replace('sm4_128_','').replace('sm4-','');
  if(!encrypt(hello,key,iv,cipherMode,profile).equals(expected))throw new Error('Hello vector mismatch');
  add('hello-'+id+'-enc',profile,'encrypt',hello,key,iv,mode,expected);
  add('hello-'+id+'-dec',profile,'decrypt',expected,key,iv,mode,hello);
}
const keys=['',explicitKey,defaultKey,'中文密钥🙂','  key  '];
for(const profile of ['default_iv','explicit_iv']){
  for(const mode of ['ecb','cbc','cfb','ofb']){
    let i=0;
    for(const n of [0,1,15,16,17,31,32,33,128,1024]){
      const key=keys[i%keys.length];
      const iv=profile==='default_iv'?['','0123456789',longIV][i%3]:['0123456789abcdef',longIV,'中文向量示例较长'][i%3];
      const data=Buffer.from(Array.from({length:n},(_,j)=>(j*73+n*19)&255));
      const ct=encrypt(data,key,iv,mode,profile);
      add(`${profile}-${mode}-${n}-enc`,profile,'encrypt',data,key,iv,'sm4-'+mode,profile==='default_iv'&&n===0?null:ct);
      add(`${profile}-${mode}-${n}-dec`,profile,'decrypt',ct,key,iv,'sm4-'+mode,profile==='default_iv'&&ct.length===0?null:data);
      i++;
    }
  }
  for(const operation of ['encrypt','decrypt']){
    for(const field of ['data','key','iv','mode']){
      const a={data:utf8('data'),key:explicitKey,iv:longIV,mode:'CBC'};a[field]=null;
      add(`${profile}-${operation}-null-${field}`,profile,operation,a.data,a.key,a.iv,a.mode,null);
    }
    for(const mode of ['','CBC ','CTR','ＧＣＭ']){
      const expected=profile==='default_iv'&&mode===''&&operation==='encrypt'?encrypt(utf8('text'),explicitKey,'','ecb',profile):null;
      add(`${profile}-${operation}-mode-${cases.length}`,profile,operation,utf8('text'),explicitKey,'',mode,expected);
    }
  }
  for(const n of [1,15,17])add(`${profile}-bad-size-${n}`,profile,'decrypt',Buffer.alloc(n),explicitKey,longIV,'CBC',null);
  for(const p of [0,17,255]){
    const ct=encrypt(Buffer.alloc(16,p),explicitKey,longIV,'cbc',profile,false);
    add(`${profile}-bad-padding-${p}`,profile,'decrypt',ct,explicitKey,longIV,'CBC',null);
  }
  const data=utf8('hello\x01中文🙂');
  const ct=encrypt(data,'  key  ',longIV,'cbc',profile);
  add(`${profile}-utf8-dec`,profile,'decrypt',ct,'  key  ',longIV,'CBC',data);
}
for(const mode of ['CBC','CFB128','OFB']){
  for(const iv of ['','short','123456789012345']){
    for(const op of ['encrypt','decrypt'])add(`explicit_iv-short-iv-${cases.length}`,'explicit_iv',op,Buffer.alloc(16),explicitKey,iv,mode,null);
  }
}
writeFileSync(new URL('./compat_vectors.json',import.meta.url),JSON.stringify({schema:1,
  oracle:'OpenSSL plus fixed known ciphertexts; string-key adapter contract',cases},null,2)+'\n');
console.log(`Generated ${cases.length} compatibility vectors`);
