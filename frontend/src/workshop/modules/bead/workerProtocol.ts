import type { WorkshopRaster } from "../../types";
import type { BeadRenderResult } from "./renderer";
import type {
  BeadProject,
  PatternClassification,
  RecognitionRequest,
  RecognitionResult,
} from "./types";

export type BeadWorkerRequest =
  | {
      id: number;
      type: "classify";
      raster: WorkshopRaster;
    }
  | {
      id: number;
      type: "recognize";
      request: RecognitionRequest;
    }
  | {
      id: number;
      type: "render";
      project: BeadProject;
      compression: number;
      pixelsPerCell: number;
    };

export type BeadWorkerResponse =
  | {
      id: number;
      ok: true;
      type: "classify";
      result: PatternClassification;
    }
  | {
      id: number;
      ok: true;
      type: "recognize";
      result: RecognitionResult;
    }
  | {
      id: number;
      ok: true;
      type: "render";
      result: BeadRenderResult;
    }
  | {
      id: number;
      ok: false;
      errorCode: string;
      message: string;
    };

export type BeadWorkerRequestType = BeadWorkerRequest["type"];

export interface BeadWorkerResultMap {
  classify: PatternClassification;
  recognize: RecognitionResult;
  render: BeadRenderResult;
}
