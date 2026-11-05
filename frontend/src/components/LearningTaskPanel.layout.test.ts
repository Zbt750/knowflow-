import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {expect,it} from 'vitest';

const theme=readFileSync(fileURLToPath(new URL('../product-theme.css',import.meta.url)),'utf8');

it('gives an open desktop study assistant a bounded floating width and wrapping header',()=>{
  expect(theme).toMatch(/@media\s*\(min-width:\s*761px\)[\s\S]*?study-assistant-dock\[open\][\s\S]*?position:\s*fixed/);
  expect(theme).toMatch(/study-assistant-dock\[open\][\s\S]*?width:\s*min\(420px,\s*calc\(100vw - 40px\)\)/);
  expect(theme).toMatch(/study-assistant-dock\[open\][\s\S]*?frog-chat-header\s*\{[^}]*flex-wrap:\s*wrap/);
  expect(theme).toMatch(/frog-chat-header-actions\s*\{[^}]*flex-wrap:\s*wrap/);
});

it('keeps the narrow-screen assistant in its existing drawer and avoids page-width overflow',()=>{
  expect(theme).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*?study-active-aside\s+\.study-assistant-dock\[open\]\s+\.task-content\s*\{[^}]*position:\s*fixed[^}]*right:\s*10px[^}]*left:\s*10px/);
  expect(theme).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*?study-assistant-dock\[open\]\s*\{\s*min-width:\s*0/);
});
