// Browser preview uses the production renderer and artwork without starting Studio.
export async function createPreview() {
  const translations = await (await fetch('./splash-text.json')).json();
  const text = Object.fromEntries(Object.entries(translations).map(([key, value]) => [key, value.zh]));
  const start = performance.now();
  return {
    async read() {
      const elapsedMs = performance.now() - start;
      const checkpoint = Math.min(8, Math.floor(elapsedMs / 1200));
      return { checkpoint, ready: checkpoint === 8, elapsedMs, history: null, version: '2.0.0', text };
    },
    finished() {},
  };
}
