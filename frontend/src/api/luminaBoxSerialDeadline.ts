export class LuminaBoxSerialTimeout extends Error {
  constructor() { super("serial_operation_timeout"); this.name = "LuminaBoxSerialTimeout"; }
}

/** Bound a platform operation; its late resource cleanup remains owned by the caller.
 * 为平台操作设置时限，迟到结果仍由调用方负责清理。
 */
export function serialDeadline<T>(operation: Promise<T>, milliseconds: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new LuminaBoxSerialTimeout()), milliseconds);
    operation.then((value) => { clearTimeout(timer); resolve(value); },
      (error: unknown) => { clearTimeout(timer); reject(error); });
  });
}
