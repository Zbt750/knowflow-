/** In-memory Vue host for component state tests. No DOM/browser/network. */
import { createRenderer, type Component } from 'vue';
export type Node = { type: string; text: string; children: Node[]; parent: Node | null; props: Record<string, unknown>; style: Record<string, string>; scrollHeight: number; scrollTop: number; open: boolean; value: unknown; multiple: boolean; selected: boolean; selectedIndex: number; options: Node[]; focus: () => void; scrollTo: () => void; querySelectorAll: () => never[]; addEventListener: () => void; tagName: string; getRootNode: () => {activeElement: null} };
function node(type: string, text = ''): Node {
  const element: Node = {type, text, children: [], parent: null, props: {}, style: {}, scrollHeight: 42, scrollTop: 0, open: true, value: '', multiple: false, selected: false, selectedIndex: -1, options: [], focus() { if(typeof document!=='undefined') Object.defineProperty(document,'activeElement',{value:element,configurable:true}); }, scrollTo() {}, querySelectorAll: () => [], addEventListener() {}, tagName: type.toUpperCase(), getRootNode: () => ({activeElement: null})};
  if (type === 'select') {
    Object.defineProperty(element, 'options', {
      get: () => element.children.filter(child => child.type === 'option'),
    });
    Object.defineProperty(element, 'selectedIndex', {
      get: () => element.options.findIndex(option => option.selected),
      set: (index: number) => element.options.forEach((option, current) => { option.selected = current === Number(index); }),
    });
  }
  return element;
}
const renderer = createRenderer<Node, Node>({
  createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (n, text) => {n.text = text;}, setElementText: (n, text) => {n.text = text; n.children = [];},
  parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
  patchProp: (n, key, _old, value) => {
    n.props[key] = value;
    // Vue's native v-model select directive reads/writes DOM properties,
    // while this state-only renderer intentionally has no browser DOM.
    // Mirror only the select/option properties that directive needs.
    if (key === 'value') n.value = value;
    if (key === 'multiple') n.multiple = Boolean(value);
    if (key === 'selected') n.selected = Boolean(value);
  },
  insertStaticContent(content, parent, anchor) {
    // Vue hoists long static template sections into a single insert operation.
    // Preserve their source text in this state-only renderer so page-level
    // state tests can mount simple templates without a browser DOM.
    const element = node('#static', content);
    element.parent = parent;
    const index = anchor ? parent.children.indexOf(anchor) : -1;
    parent.children.splice(index < 0 ? parent.children.length : index, 0, element);
    return [element, element];
  },
  insert(n, parent, anchor = null) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, n); },
  remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null; },
});
export function mountStateComponent(component: Component, props: Record<string, unknown>) {
  const root = node('root'); const app = renderer.createApp(component, props); app.mount(root);
  return {root, unmount: () => app.unmount()};
}
export function all(root: Node): Node[] {return [root, ...root.children.flatMap(all)];}
export function text(root: Node): string {return root.type === '#comment' ? '' : root.text + root.children.map(text).join('');}
export function deferred<T>() {let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};}
export async function flush() {for (let i = 0; i < 20; i++) await Promise.resolve();}
