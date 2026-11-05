import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {it,expect} from 'vitest';
const theme=readFileSync(fileURLToPath(new URL('../product-theme.css',import.meta.url)),'utf8');
it('desktop default panel floats at the upper right without claiming a flex track',()=>{
 const desktop=theme.slice(theme.indexOf('@media(min-width:761px){',theme.indexOf('.study-assistant-dock .task-draft'))).split('@media(max-width:760px)')[0];
 expect(desktop).not.toContain('flex:1 1 520px');
 expect(desktop).toMatch(/position:\s*fixed/);
 expect(desktop).toMatch(/right:\s*20px/);
 expect(desktop).toMatch(/width:\s*min\(420px/);
 expect(desktop).toMatch(/overflow-y:\s*auto/);
 expect(desktop).toMatch(/frog-composer\s*\{[^}]*flex:\s*0 0 auto/);
});
