// Original business assertions, only isolated coordinates/date/output are bound.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const file=path.join(__dirname,'naiwa-v32-operations.cjs');
let source=fs.readFileSync(file,'utf8').replaceAll('naiwa-v32-20261022','naiwa-v33-closeout-20261023')
 .replaceAll('63246','55222').replaceAll('63245','55221')
 .replace("read(path.join(out,'runtime-'+epoch+'/window.json')).nonce","'isolated-fixed-no-paid-authorization'")
 .replace("const original=await get('/api/plans/today');assert.equal(original.total_count,1);","const original=await get('/api/plans/today');assert.equal(original.total_count,0);")
 .replaceAll('total_count,1','total_count,0').replaceAll('total_count,2','total_count,1').replaceAll('total_count,3','total_count,2')
 .replace("assert.equal(original.total_count,0)","assert.equal(original.status,'setup');assert(original.recommendations.length>0)")
 .replaceAll("assert.equal((await get('/api/plans/today')).total_count,0)","assert.equal((await get('/api/plans/today')).status,'setup')")
 .replace('for(const old of original.items)','for(const old of (original.items||[]))')
 // With an empty day this journey adds two candidates, so stock is not exhausted.
 .replaceAll("assert.equal(noneTask.status,'needs_info');assert.equal(noneTask.draft,null);","assert.equal(noneTask.status,'ready');assert(noneTask.draft);")
 .replaceAll("assert(noneTask.message.includes('可新增 0 道'));","assert(noneTask.message.includes('确认'));")
 .replace('actualInventoryExhausted:true','remainingInventoryPreview:true')
 .replace("finally{console.log('VISIBLE_OPERATIONS_EVIDENCE',dir)}","finally{await browser.close();console.log('VISIBLE_OPERATIONS_EVIDENCE',dir)}");
process.env.NAIWA_V32_EPOCH=process.env.NAIWA_CLOSEOUT_ATTEMPT||'closeout-2';process.env.NAIWA_V32_STUDY_DATE='2040-04-03';
const m=new Module(file,module);m.filename=file;m.paths=Module._nodeModulePaths(__dirname);m._compile(source,file);
