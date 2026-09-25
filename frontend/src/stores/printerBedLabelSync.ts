type PrinterBedLabelSynchronizer = (printerId: string) => void;

let synchronizePrinterBedLabelHandler: PrinterBedLabelSynchronizer | null = null;

export function registerPrinterBedLabelSynchronizer(
  handler: PrinterBedLabelSynchronizer,
): void {
  synchronizePrinterBedLabelHandler = handler;
}

export function synchronizePrinterBedLabel(printerId: string): void {
  synchronizePrinterBedLabelHandler?.(printerId);
}
