import { describe, expect, it, vi } from "vitest";

import {
  BeadWorkerClient,
  BeadWorkerClientError,
  type BeadWorkerLike,
} from "../workshop/modules/bead/workerClient";
import type {
  BeadWorkerRequest,
  BeadWorkerResponse,
} from "../workshop/modules/bead/workerProtocol";
import type { WorkshopRaster } from "../workshop/types";

class FakeWorker implements BeadWorkerLike {
  onmessage:
    | ((event: MessageEvent<BeadWorkerResponse>) => void)
    | null = null;

  onerror: ((event: ErrorEvent) => void) | null = null;

  readonly posted: Array<{
    message: BeadWorkerRequest;
    transfer: Transferable[];
  }> = [];

  readonly terminate = vi.fn();

  postMessage(
    message: BeadWorkerRequest,
    transfer: Transferable[] = [],
  ): void {
    this.posted.push({ message, transfer });
  }

  emit(message: BeadWorkerResponse): void {
    this.onmessage?.(
      { data: message } as MessageEvent<BeadWorkerResponse>,
    );
  }
}

function raster(): WorkshopRaster {
  return {
    width: 2,
    height: 2,
    data: new Uint8ClampedArray([
      0, 0, 0, 255,
      255, 0, 0, 255,
      0, 255, 0, 255,
      0, 0, 255, 255,
    ]),
  };
}

describe("bead worker client", () => {
  it("cancels older requests and ignores their late responses", async () => {
    const worker = new FakeWorker();
    const client = new BeadWorkerClient(() => worker);
    const first = client.classify(raster());
    const second = client.classify(raster());

    expect(second.id).toBe(first.id + 1);
    client.cancelBefore(second.id);
    await expect(first.promise).rejects.toMatchObject({
      code: "request-cancelled",
    });

    worker.emit({
      id: first.id,
      ok: true,
      type: "classify",
      result: {
        mode: "hard-pixel",
        confidence: 0.9,
        scores: {
          "numbered-grid": 0,
          "hard-pixel": 0.9,
          "ring-preview": 0,
        },
      },
    });
    worker.emit({
      id: second.id,
      ok: true,
      type: "classify",
      result: {
        mode: "ring-preview",
        confidence: 0.95,
        scores: {
          "numbered-grid": 0,
          "hard-pixel": 0.1,
          "ring-preview": 0.95,
        },
      },
    });

    await expect(second.promise).resolves.toMatchObject({
      mode: "ring-preview",
    });
  });

  it("transfers a private raster copy without detaching the caller source", () => {
    const worker = new FakeWorker();
    const client = new BeadWorkerClient(() => worker);
    const source = raster();

    client.classify(source);

    const posted = worker.posted[0];
    expect(posted?.message.type).toBe("classify");
    if (posted?.message.type !== "classify") {
      throw new Error("expected classify request");
    }
    expect(posted.message.raster.data).not.toBe(source.data);
    expect(posted.message.raster.data).toEqual(source.data);
    expect(posted.transfer).toEqual([
      posted.message.raster.data.buffer,
    ]);
    expect(source.data.byteLength).toBe(16);
  });

  it("rejects worker failures with a stable error code", async () => {
    const worker = new FakeWorker();
    const client = new BeadWorkerClient(() => worker);
    const task = client.classify(raster());

    worker.emit({
      id: task.id,
      ok: false,
      errorCode: "invalid-raster",
      message: "Raster is invalid.",
    });

    await expect(task.promise).rejects.toEqual(
      expect.objectContaining({
        name: "BeadWorkerClientError",
        code: "invalid-raster",
      }),
    );
  });

  it("disposes exactly once and rejects every outstanding task", async () => {
    const worker = new FakeWorker();
    const client = new BeadWorkerClient(() => worker);
    const first = client.classify(raster());
    const second = client.classify(raster());

    client.dispose();
    client.dispose();

    await expect(first.promise).rejects.toBeInstanceOf(
      BeadWorkerClientError,
    );
    await expect(first.promise).rejects.toMatchObject({
      code: "worker-disposed",
    });
    await expect(second.promise).rejects.toMatchObject({
      code: "worker-disposed",
    });
    expect(worker.terminate).toHaveBeenCalledTimes(1);
    expect(() => client.classify(raster())).toThrowError(
      expect.objectContaining({ code: "worker-disposed" }),
    );
  });
});
