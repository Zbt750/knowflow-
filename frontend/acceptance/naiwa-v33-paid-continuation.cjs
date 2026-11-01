/* Rebind the original visible-Chrome UI driver to an append-only V33 run.
 * It continues to type into the real Vue page; no HTTP message shortcut is added.
 */
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const root = path.resolve(__dirname, '../..');
const source = path.join(__dirname, 'naiwa-agent-full-v3.cjs');
const tag = process.env.NAIWA_V33_CONTINUATION_TAG || 'r3';
if (!/^[a-z0-9-]{1,24}$/.test(tag)) throw new Error('invalid continuation tag');
const outPath = `storage/quality-audits/naiwa-v33-closeout-20261023/paid-continuation-${tag}`;
const runPath = `storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-${tag}`;
const ledgerPath = `storage/quality-audits/naiwa-freeze-preflight-20261021/round40-v33-exploratory-${tag}/provider-ledger.json`;
let code = fs.readFileSync(source, 'utf8');
code = code.replace(
  "storage/quality-audits/naiwa-freeze-preflight-20261021/naiwa-v3-20261022",
  outPath,
);
code = code.replace(
  "storage/manual-experience/naiwa-real-20261020/agent-full-v3-20261022",
  runPath,
);
code = code.replace(
  "storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021/provider-ledger.json",
  ledgerPath,
);
if (code.includes('naiwa-v3-20261022') || code.includes('agent-full-v3-20261022') ||
    code.includes('round40-agent-full-v2-20261021/provider-ledger.json')) {
  throw new Error('V33 driver path rebinding incomplete');
}
const instance = new Module(source, module);
instance.filename = source;
instance.paths = Module._nodeModulePaths(__dirname);
instance._compile(code, source);
