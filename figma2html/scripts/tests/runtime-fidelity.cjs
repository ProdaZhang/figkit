/* DOM double: structural regression checks, not pixel/browser acceptance. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class El {
  constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.style={};this.dataset={};this._text='';}
  set textContent(t){this._text=t;this.children=[];} get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return this.attrs[k];}
  get attributes(){return Object.entries(this.attrs).map(([name,value])=>({name,value}));}
  appendChild(c){this.children.push(c);return c;}
  querySelectorAll(sel){let out=[];for(const c of this.children){if(sel==='*'||sel===c.tag||(sel==='[id]'&&c.attrs.id))out.push(c);out.push(...c.querySelectorAll(sel));}return out;}
  cloneNode(){const n=new El(this.tag);n.attrs={...this.attrs};n.style={...this.style};n.dataset={...this.dataset};n._text=this._text;n.children=this.children.map(c=>c.cloneNode());return n;}
}
const ctx={window:{},document:{createElement:t=>new El(t),createElementNS:(_,t)=>new El(t)},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../../runtime/render.js'),'utf8'),ctx);
const vector={id:'same:id',parent:'',x:0,y:0,w:20,h:10,z:1,opacity:1,paths:[{d:'M0 0L20 0L10 10Z',fill:'#fff',rule:'nonzero'},{d:'M0 0L20 0L10 10Z',fill:'#000',rule:'nonzero',clip:'inside'}],shadow:'0 4px 4px #000',vectorShadows:[{x:0,y:4,blur:2,spread:1,color:'#000'}]};
const mounts=[new El('div'),new El('div')];for(const m of mounts)ctx.renderScreen({els:[vector]},m);
const clone=mounts[0].cloneNode();ctx.namespaceSvgIds(clone);mounts.push(clone);
const all=mounts.flatMap(m=>m.querySelectorAll('*'));
const ids=all.filter(e=>e.attrs.id).map(e=>e.attrs.id);assert.equal(ids.length,new Set(ids).size);
for(const mount of mounts){const local=mount.querySelectorAll('*');const localIds=new Set(local.map(e=>e.attrs.id));for(const e of local)for(const a of e.attributes){const refs=[...a.value.matchAll(/url\(#([^)]*)\)/g)];for(const r of refs)assert(localIds.has(r[1]));}}
assert.equal(mounts[0].children[0].style.boxShadow,undefined);assert(all.some(e=>e.tag==='feMorphology'));
const cap={els:[{id:'p',parent:'',x:0,y:0,w:50,h:40,z:1,opacity:1,matrix:[0,1,-1,0,90,20]},
{id:'c',parent:'p',x:0,y:0,w:20,h:10,z:2,opacity:1,matrix:[0,1,1,0,78,25]}]};
const m=new El('div');ctx.renderScreen(cap,m);assert.equal(m.children[0].children[0].style.transform,'matrix(1,0,0,-1,5,12)');
const sub=new El('div');ctx.renderScreen(ctx.subtreeOf(cap,'c'),sub);assert.equal(sub.children[0].style.transform,'matrix(0,1,1,0,78,25)');
const text={content:'AB',color:'#fff',size:12,weight:400,family:'Test',runs:[{content:'A',decoration:'underline',color:'#f00',size:12,weight:400,family:'Test',ls:0},{content:'B',decoration:'line-through',color:'#fff',size:14,weight:700,family:'Test',ls:1}]};
const t=new El('div');ctx.applyRecStyle({text,opacity:1},t);assert.equal(t.textContent,'AB');assert.equal(t.children[0].children[1].style.textDecorationLine,'line-through');
const plain=new El('div');ctx.applyRecStyle({text:{...text,runs:undefined,decoration:'line-through'},opacity:1},plain);plain.textContent='NEW';assert.equal(plain.style.textDecorationLine,'line-through');
console.log('OK: instance IDs, clone references, vector filters, nested matrices, subtree extraction, text runs.');
