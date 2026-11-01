/* Reuse the actual visible-Chrome UI driver without changing historic V2.
 * Input/send still use Vue controls; only artifact/runtime paths are rebound.
 */
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const out=path.join(root,'storage/quality-audits/naiwa-freeze-preflight-20261021/naiwa-v3-20261022');
const run=path.join(root,'storage/manual-experience/naiwa-real-20261020/agent-full-v3-20261022');
const ledger=path.join(root,'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021/provider-ledger.json');
const source=path.join(__dirname,'naiwa-agent-full-v2.cjs');
let code=fs.readFileSync(source,'utf8');
code=code.replace("const OUT = path.join(ROOT, 'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021');",`const OUT = ${JSON.stringify(out)};`);
code=code.replace("const RUN = path.join(ROOT, 'storage/manual-experience/naiwa-real-20261020/agent-full-v2-20261021');",`const RUN = ${JSON.stringify(run)};`);
code=code.replaceAll("path.join(OUT,'provider-ledger.json')",JSON.stringify(ledger));
code=code.replace("const before=read("+JSON.stringify(ledger)+");", "const before=read("+JSON.stringify(ledger)+"); if(scene==='A' && before.requests.filter(r=>r.case_id==='A').length>=3) throw Error('V3 A3 cap');");
if(code.includes("const OUT = path.join(ROOT,")||code.includes("path.join(OUT,'provider-ledger.json')"))throw Error('V3 driver binding incomplete');
const moduleInstance=new Module(source,module);
moduleInstance.filename=source;moduleInstance.paths=module.paths;
moduleInstance._compile(code,source);
