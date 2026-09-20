const test = require('node:test');
const assert = require('node:assert/strict');
const security = require('../workshop-security.cjs');
const { fetchNativeBedModel } = require('../bed-model-bridge.cjs');

test('workshop trusts only the selected backend port for host and internal requests', () => {
  security.enableManagedDesktopHost(8012);
  assert.equal(security.isAllowedWorkshopIpcSender('http://127.0.0.1:8012/'), true);
  assert.equal(security.isAllowedWorkshopIpcSender('http://127.0.0.1:8000/'), false);
  for (const port of [8012, 8000]) {
    assert.equal(security.isAllowedWorkshopRequest({ trustedInternal: true, url: `http://127.0.0.1:${port}/api/workshop/v1/modules/example/1.0.0/runtime` }), port === 8012);
    assert.equal(security.isAllowedWorkshopRequest({ trustedInternal: true, url: `http://127.0.0.1:${port}/api/system/machine-registry/bed-model?device_profile_id=test` }), port === 8012);
  }
});

test('native bed bridge fetches the selected backend origin', async () => {
  let requested;
  await fetchNativeBedModel({ deviceProfileId: 'test', backendOrigin: 'http://127.0.0.1:8012', fetchImpl: async url => { requested = url; return { status: 404 }; } });
  assert.equal(requested, 'http://127.0.0.1:8012/api/system/machine-registry/bed-model?device_profile_id=test');
});
