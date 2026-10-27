/** The mark's print grid: every image is 150 x 207 print pixels. */
export const MARK_WIDTH = 150;
export const MARK_HEIGHT = 207;
/**
 * Largest crisp size for the box: each print pixel covers a whole number of physical pixels
 * at the current display scaling (devicePixelRatio 1, 1.25, 1.5, 1.75, 2, ...).
 * `overshoot` lets a soft box grow by up to that fraction to reach the next crisp size.
 */
export function fitMark(boxWidth, boxHeight, devicePixelRatio, overshoot = 0) {
    const dpr = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
    const fit = Math.min((Math.max(0, boxWidth) * dpr) / MARK_WIDTH, (Math.max(0, boxHeight) * dpr) / MARK_HEIGHT);
    const cell = Math.max(1, Math.floor(fit * (1 + Math.max(0, overshoot)) + 1e-6));
    const deviceWidth = MARK_WIDTH * cell;
    const deviceHeight = MARK_HEIGHT * cell;
    return { cell, deviceWidth, deviceHeight, cssWidth: deviceWidth / dpr, cssHeight: deviceHeight / dpr };
}
/** CSS offset that moves a box starting at `cssPosition` onto a whole physical pixel. */
export function snapOffset(cssPosition, devicePixelRatio) {
    const device = cssPosition * devicePixelRatio;
    return (Math.round(device) - device) / devicePixelRatio;
}
