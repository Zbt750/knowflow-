// Reuse prior GET-only browser assertions without overwriting prior evidence.
const fs=require('node:fs'),path=require('node:path');
const prior=path.resolve('storage/quality-audits/naiwa-proxy-attribution-zero-20261021');
const current=path.resolve('storage/quality-audits/naiwa-final-zero-precheck-20261021');
let source=fs.readFileSync('scripts/naiwa_proxy_readonly_browser_20261021.cjs','utf8');
source=source.replace("const out=path.resolve('storage/quality-audits/naiwa-proxy-attribution-zero-20261021');",'const out='+JSON.stringify(current)+';');
source=source.replace("path.join(out,'asgi-regression.json')",JSON.stringify(path.join(prior,'asgi-regression.json')));
new Function('require',source)(require);
