/**
 * Startup pacing for the launch animation. The Lumina mark is built from 10 printed layers.
 * Real checkpoints (from the app's status file) are the only facts; between them a virtual
 * clock walks the previous launch's timeline, so a launch like the last one lands layers
 * evenly. The clock slows down instead of running far past a checkpoint that has not
 * happened, and catches up smoothly when one arrives early.
 * Hard limits: at most L8 before the backend is healthy, at most L9 before the window is ready.
 */
export const LAYERS = 10;
export const CHECKPOINT = {
    launchPressed: 0,
    portSelected: 1,
    backendSpawned: 2,
    backendPython: 3,
    backendWorkers: 4,
    backendHealthy: 5,
    storageReady: 6,
    windowCreated: 7,
    windowReady: 8,
};
const COUNT = 9;
const CHECKPOINT_LAYERS = [1, 1, 2, 3, 5, 7, 8, 9, 10];
/** Without history assume a cold first launch, so a long wait is spread across layers. */
export const DEFAULT_TIMINGS = [0, 200, 400, 1500, 15000, 15500, 15800, 16100, 17000];
const MIN_TOTAL_MS = 300;
const MAX_TOTAL_MS = 300000;
const CATCH_UP_PER_MS = 0.0018;
const OVERRUN_SOFTNESS = 0.12;
/** A copy of valid checkpoint timings (ms from Launch), or null. */
export function normalizeTimings(raw) {
    if (!Array.isArray(raw) || raw.length !== COUNT || raw[0] !== 0)
        return null;
    for (let i = 1; i < COUNT; i++) {
        if (typeof raw[i] !== 'number' || !Number.isFinite(raw[i]) || raw[i] < raw[i - 1])
            return null;
    }
    const total = raw[COUNT - 1];
    return total >= MIN_TOTAL_MS && total <= MAX_TOTAL_MS ? raw.slice() : null;
}
const REPLAY_STEP_MS = 16;
export function createPacer(history) {
    const expected = normalizeTimings(history) ?? DEFAULT_TIMINGS.slice();
    const total = expected[COUNT - 1];
    const softness = OVERRUN_SOFTNESS * total;
    let reached = 0;
    let virtual = 0;
    let last = null;
    const pacer = {
        reach(checkpoint) {
            if (Number.isInteger(checkpoint) && checkpoint >= 0 && checkpoint < COUNT)
                reached = Math.max(reached, checkpoint);
        },
        fastForward(now) {
            // step() caps each delta at 100 ms, so replay in frame-sized steps to keep its slow-down rules.
            for (let at = last ?? 0; at < now; at = Math.min(now, at + REPLAY_STEP_MS))
                pacer.step(Math.min(now, at + REPLAY_STEP_MS));
        },
        step(now) {
            const dt = last === null ? 0 : Math.min(100, Math.max(0, now - last));
            last = now;
            if (reached >= CHECKPOINT.windowReady)
                return LAYERS;
            const nextAt = expected[reached + 1];
            const rate = virtual < nextAt ? 1 : 1 / Math.pow(1 + (virtual - nextAt) / softness, 2);
            virtual += dt * rate;
            const floor = expected[reached];
            if (virtual < floor)
                virtual += (floor - virtual) * Math.min(1, dt * CATCH_UP_PER_MS);
            virtual = Math.min(virtual, total);
            const layer = 1 + Math.floor(((LAYERS - 1) * virtual) / total + 1e-9);
            return Math.min(Math.max(layer, CHECKPOINT_LAYERS[reached]), reached < CHECKPOINT.backendHealthy ? LAYERS - 2 : LAYERS - 1);
        },
        reached: () => reached,
    };
    return pacer;
}
