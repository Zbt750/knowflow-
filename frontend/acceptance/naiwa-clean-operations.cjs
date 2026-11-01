const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const ROOT=path.resolve(__dirname,'../..');
const identity=JSON.parse(fs.readFileSync(path.join(ROOT,'storage/manual-experience/naiwa-clean-20261023/identity.json')));
const file=path.join(__dirname,'naiwa-v32-operations.cjs');
let source=fs.readFileSync(file,'utf8').replaceAll('naiwa-v32-20261022','naiwa-v33-continue-20261023')
 .replaceAll('63246',String(identity.web_port)).replaceAll('63245',String(identity.api_port))
 .replace("read(path.join(out,'runtime-'+epoch+'/window.json')).nonce","'clean-offline-no-paid-authorization'");
const m=new Module(file,module);m.filename=file;m.paths=Module._nodeModulePaths(__dirname);m._compile(source,file);
