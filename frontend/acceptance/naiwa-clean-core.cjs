// Replay unchanged business assertions; only local environment coordinates differ.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const ROOT=path.resolve(__dirname,'../..'),OUT=path.join(ROOT,'storage/quality-audits/naiwa-v33-continue-20261023');
const identity=JSON.parse(fs.readFileSync(path.join(ROOT,'storage/manual-experience/naiwa-clean-20261023/identity.json')));
const original=path.join(__dirname,'naiwa-v33-final.cjs');
let source=fs.readFileSync(original,'utf8').replaceAll('naiwa-v33-final-20261023','naiwa-v33-continue-20261023')
 .replaceAll('visible-ui-1','visible-core').replaceAll('63246',String(identity.web_port)).replaceAll('63245',String(identity.api_port))
 .replaceAll('2040-03-02T01:00:00Z','2040-04-02T01:00:00Z')
 .replace("JSON.parse(fs.readFileSync(path.join(RUN,'window.json'))).nonce","'clean-offline-no-paid-authorization'");
const m=new Module(original,module);m.filename=original;m.paths=Module._nodeModulePaths(__dirname);m._compile(source,original);
