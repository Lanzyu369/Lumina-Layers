const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '../..', name), 'utf8');
test('all generated exports adopt controlled saving', () => {
  const flow = read('frontend/src/recipe/importFlow.ts');
  assert.match(flow, /saveGeneratedFile\(shareCardBlob, filename, ['"]share-card['"]\)/);
  assert.match(flow, /saveGeneratedFile\(blob, filename, ['"]project['"]\)/);
  assert.match(read('frontend/src/components/Scene3D.tsx'), /saveGeneratedFile\(/);
});
