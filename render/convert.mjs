import fs from 'fs';
import occtimportjs from 'occt-import-js';
const occt = await occtimportjs();
const buf = new Uint8Array(fs.readFileSync('DE1PROV14.STEP'));
const t0 = Date.now();
const res = occt.ReadStepFile(buf, { linearUnit: 'millimeter', linearDeflectionType: 'bounding_box_ratio', linearDeflection: 0.0008, angularDeflection: 0.35 });
console.log('success', res.success, 'meshes', res.meshes.length, 'sec', (Date.now()-t0)/1000);
// flatten node tree to get mesh -> path names
const names = {};
function walk(n, path) {
  const p = path ? `${path}/${n.name}` : n.name;
  for (const m of n.meshes || []) names[m] = p;
  for (const c of n.children || []) walk(c, p);
}
walk(res.root, '');
const out = res.meshes.map((m, i) => ({
  name: names[i] || m.name, color: m.color || null,
  pos: Array.from(m.attributes.position.array), idx: Array.from(m.index.array),
  brep_faces: (m.brep_faces || []).map(f => ({ first: f.first, last: f.last, color: f.color }))
}));
fs.writeFileSync('de1.json', JSON.stringify(out));
const summary = {};
for (const o of out) { const k = o.name; summary[k] = (summary[k] || 0) + o.idx.length / 3; }
console.log(Object.entries(summary).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${v}\t${k}`).join('\n'));
