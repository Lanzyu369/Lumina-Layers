import type {
  WorkshopProjectRecord,
  WorkshopProjectStorage,
} from "./types";
import { WORKSHOP_RECIPE_ENVELOPE_MAX_BYTES } from "../recipe/types";

const DEFAULT_DATABASE_NAME = "lumina-workshop";
const DATABASE_VERSION = 2;
const PROJECT_STORE = "projects";
const SNAPSHOT_STORE = "snapshots";
const METADATA_STORE = "metadata";
const UPDATED_AT_INDEX = "updatedAt";
const MODULE_ID_INDEX = "moduleId";
const MAX_ESTIMATE_DEPTH = 100;

export const WORKSHOP_MODULE_QUOTA_BYTES = 256 * 1024 * 1024;
export const WORKSHOP_RECORD_QUOTA_BYTES = 64 * 1024 * 1024;
export const WORKSHOP_RECIPE_QUOTA_BYTES =
  WORKSHOP_RECIPE_ENVELOPE_MAX_BYTES;

export type WorkshopProjectStorageErrorCode =
  | "project-value-invalid"
  | "project-record-too-large"
  | "project-quota-exceeded"
  | "project-recipe-too-large"
  | "project-snapshot-not-found";

export class WorkshopProjectStorageError extends Error {
  readonly code: WorkshopProjectStorageErrorCode;
  readonly limitBytes: number | undefined;
  readonly actualBytes: number | undefined;

  constructor(
    code: WorkshopProjectStorageErrorCode,
    message: string,
    limitBytes?: number,
    actualBytes?: number,
  ) {
    super(message);
    this.name = "WorkshopProjectStorageError";
    this.code = code;
    this.limitBytes = limitBytes;
    this.actualBytes = actualBytes;
  }
}

export interface WorkshopProjectStorageLimits {
  moduleQuotaBytes: number;
  recordQuotaBytes: number;
  recipeQuotaBytes: number;
}

export interface ManagedWorkshopProjectStorage
  extends WorkshopProjectStorage {
  snapshotModule(moduleId: string, version: string): Promise<string>;
  restoreSnapshot(moduleId: string, snapshotId: string): Promise<void>;
  deleteSnapshot(moduleId: string, snapshotId: string): Promise<void>;
  deleteModuleProjects(moduleId: string): Promise<void>;
}

interface StoredWorkshopProject<TProject = unknown>
  extends WorkshopProjectRecord<TProject> {
  key: string;
}

interface StoredWorkshopSnapshot {
  key: string;
  moduleId: string;
  snapshotId: string;
  version: string;
  createdAt: string;
  projects: WorkshopProjectRecord<unknown>[];
  projectBytes: number;
}

interface StoredWorkshopMetadata {
  key: string;
  moduleId: string;
  kind: "project-usage" | "snapshot";
  bytes: number;
  updatedAt: string;
}

export interface WorkshopProjectStorageResult {
  storage: ManagedWorkshopProjectStorage;
  persistent: boolean;
  status: "available" | "persistence-unavailable";
}

function projectKey(moduleId: string, projectId: string): string {
  return `${moduleId}:${projectId}`;
}

function snapshotKey(moduleId: string, snapshotId: string): string {
  return JSON.stringify([moduleId, snapshotId]);
}

function usageMetadataKey(moduleId: string): string {
  return `project-usage:${moduleId}`;
}

function snapshotMetadataKey(
  moduleId: string,
  snapshotId: string,
): string {
  return `snapshot:${snapshotKey(moduleId, snapshotId)}`;
}

function withoutStorageKey<TProject>(
  stored: StoredWorkshopProject<TProject>,
): WorkshopProjectRecord<TProject> {
  const { key: _key, ...record } = stored;
  return record;
}

function normalizedLimits(
  options: Partial<WorkshopProjectStorageLimits>,
): WorkshopProjectStorageLimits {
  const limits = {
    moduleQuotaBytes:
      options.moduleQuotaBytes ?? WORKSHOP_MODULE_QUOTA_BYTES,
    recordQuotaBytes:
      options.recordQuotaBytes ?? WORKSHOP_RECORD_QUOTA_BYTES,
    recipeQuotaBytes:
      options.recipeQuotaBytes ?? WORKSHOP_RECIPE_QUOTA_BYTES,
  };
  for (const [name, value] of Object.entries(limits)) {
    if (!Number.isSafeInteger(value) || value <= 0) {
      throw new TypeError(`${name} must be a positive safe integer.`);
    }
  }
  return limits;
}

function invalidStoredValue(message: string): never {
  throw new WorkshopProjectStorageError(
    "project-value-invalid",
    message,
  );
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isBlobValue(value: object): value is Blob {
  return (
    (typeof Blob !== "undefined" && value instanceof Blob) ||
    Object.prototype.toString.call(value) === "[object Blob]"
  );
}

interface EstimateState {
  active: WeakSet<object>;
  visited: WeakSet<object>;
}

function estimateValue(
  value: unknown,
  state: EstimateState,
  depth: number,
): number {
  if (depth > MAX_ESTIMATE_DEPTH) {
    return invalidStoredValue("Stored project nesting is too deep.");
  }
  if (value === null || value === undefined) {
    return 0;
  }
  switch (typeof value) {
    case "string":
      return utf8Bytes(value);
    case "number":
    case "bigint":
      return 8;
    case "boolean":
      return 1;
    case "symbol":
    case "function":
      return invalidStoredValue(
        "Stored projects must contain structured-clone values only.",
      );
    case "object":
      break;
    default:
      return invalidStoredValue("Stored project value is unsupported.");
  }

  const objectValue = value as object;
  if (state.active.has(objectValue)) {
    return invalidStoredValue(
      "Stored projects must not contain cyclic values.",
    );
  }
  if (state.visited.has(objectValue)) {
    return 0;
  }
  state.active.add(objectValue);
  let bytes: number;
  try {
    if (value instanceof ArrayBuffer) {
      bytes = value.byteLength;
    } else if (
      typeof SharedArrayBuffer !== "undefined" &&
      value instanceof SharedArrayBuffer
    ) {
      bytes = value.byteLength;
    } else if (ArrayBuffer.isView(value)) {
      bytes = value.byteLength;
    } else if (isBlobValue(value)) {
      bytes = value.size;
    } else if (value instanceof Date) {
      if (Number.isNaN(value.getTime())) {
        return invalidStoredValue(
          "Stored projects must not contain invalid dates.",
        );
      }
      bytes = 8;
    } else if (value instanceof RegExp) {
      bytes = utf8Bytes(value.source) + utf8Bytes(value.flags);
    } else if (value instanceof Map) {
      bytes = 8;
      for (const [key, item] of value.entries()) {
        bytes += estimateValue(key, state, depth + 1);
        bytes += estimateValue(item, state, depth + 1);
      }
    } else if (value instanceof Set) {
      bytes = 8;
      for (const item of value.values()) {
        bytes += estimateValue(item, state, depth + 1);
      }
    } else if (Array.isArray(value)) {
      bytes = 8;
      for (const item of value) {
        bytes += estimateValue(item, state, depth + 1);
      }
    } else {
      const prototype = Object.getPrototypeOf(value);
      if (prototype !== Object.prototype && prototype !== null) {
        return invalidStoredValue(
          "Stored projects must not contain class instances.",
        );
      }
      bytes = 8;
      for (const key of Reflect.ownKeys(value)) {
        if (typeof key !== "string") {
          return invalidStoredValue(
            "Stored projects must not contain symbol keys.",
          );
        }
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (
          descriptor?.get !== undefined ||
          descriptor?.set !== undefined
        ) {
          return invalidStoredValue(
            "Stored projects must not contain accessors.",
          );
        }
        if (descriptor?.enumerable) {
          bytes += utf8Bytes(key);
          bytes += estimateValue(
            (value as Record<string, unknown>)[key],
            state,
            depth + 1,
          );
        }
      }
    }
  } finally {
    state.active.delete(objectValue);
  }
  state.visited.add(objectValue);
  return bytes;
}

export function estimateStoredBytes(value: unknown): number {
  return estimateValue(
    value,
    {
      active: new WeakSet<object>(),
      visited: new WeakSet<object>(),
    },
    0,
  );
}

export function assertWorkshopRecipeEnvelopeWithinQuota(
  envelope: unknown,
  limitBytes = WORKSHOP_RECIPE_QUOTA_BYTES,
): void {
  const actualBytes = estimateStoredBytes(envelope);
  if (actualBytes > limitBytes) {
    throw new WorkshopProjectStorageError(
      "project-recipe-too-large",
      "Workshop recipe envelope exceeds its byte limit.",
      limitBytes,
      actualBytes,
    );
  }
}

function validateNamespaceValue(
  value: string,
  label: string,
  maximumLength: number,
): void {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maximumLength ||
    value.includes("\0")
  ) {
    invalidStoredValue(`${label} is invalid.`);
  }
}

function validateRecord(
  record: WorkshopProjectRecord<unknown>,
): void {
  validateNamespaceValue(record.moduleId, "moduleId", 128);
  validateNamespaceValue(record.projectId, "projectId", 256);
  validateNamespaceValue(record.schemaVersion, "schemaVersion", 128);
  validateNamespaceValue(record.createdAt, "createdAt", 64);
  validateNamespaceValue(record.updatedAt, "updatedAt", 64);
}

function cloneValue<T>(value: T): T {
  try {
    return structuredClone(value);
  } catch (error) {
    throw new WorkshopProjectStorageError(
      "project-value-invalid",
      error instanceof Error
        ? `Stored project is not cloneable: ${error.message}`
        : "Stored project is not cloneable.",
    );
  }
}

function preparedRecord<TProject>(
  record: WorkshopProjectRecord<TProject>,
  limits: WorkshopProjectStorageLimits,
): {
  record: WorkshopProjectRecord<TProject>;
  bytes: number;
} {
  validateRecord(record);
  const bytes = estimateStoredBytes(record);
  if (bytes > limits.recordQuotaBytes) {
    throw new WorkshopProjectStorageError(
      "project-record-too-large",
      "Workshop project record exceeds its byte limit.",
      limits.recordQuotaBytes,
      bytes,
    );
  }
  return {
    record: cloneValue(record),
    bytes,
  };
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new Error("IndexedDB request failed."));
  });
}

function transactionComplete(
  transaction: IDBTransaction,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () =>
      reject(
        transaction.error ??
          new Error("IndexedDB transaction aborted."),
      );
    transaction.onerror = () =>
      reject(
        transaction.error ??
          new Error("IndexedDB transaction failed."),
      );
  });
}

async function abortTransaction(
  transaction: IDBTransaction,
  completion: Promise<void>,
): Promise<void> {
  try {
    transaction.abort();
  } catch {
    // A completed transaction already has no mutations left to roll back.
  }
  try {
    await completion;
  } catch {
    // The caller throws the typed domain error after rollback converges.
  }
}

function readStoredProjectsForModule(
  store: IDBObjectStore,
  moduleId: string,
): Promise<StoredWorkshopProject<unknown>[]> {
  return new Promise((resolve, reject) => {
    const projects: StoredWorkshopProject<unknown>[] = [];
    const request = store.index(MODULE_ID_INDEX).openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) {
        resolve(projects);
        return;
      }
      const candidate =
        cursor.value as StoredWorkshopProject<unknown>;
      if (candidate.moduleId === moduleId) {
        projects.push(candidate);
      }
      cursor.continue();
    };
    request.onerror = () =>
      reject(
        request.error ?? new Error("IndexedDB project cursor failed."),
      );
  });
}

function readStoredSnapshotsForModule(
  store: IDBObjectStore,
  moduleId: string,
): Promise<StoredWorkshopSnapshot[]> {
  return new Promise((resolve, reject) => {
    const snapshots: StoredWorkshopSnapshot[] = [];
    const request = store.index(MODULE_ID_INDEX).openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) {
        resolve(snapshots);
        return;
      }
      const candidate = cursor.value as StoredWorkshopSnapshot;
      if (candidate.moduleId === moduleId) {
        snapshots.push(candidate);
      }
      cursor.continue();
    };
    request.onerror = () =>
      reject(
        request.error ?? new Error("IndexedDB snapshot cursor failed."),
      );
  });
}

function projectBytes(
  projects: readonly WorkshopProjectRecord<unknown>[],
): number {
  return projects.reduce(
    (total, project) => total + estimateStoredBytes(project),
    0,
  );
}

function usageMetadata(
  moduleId: string,
  bytes: number,
): StoredWorkshopMetadata {
  return {
    key: usageMetadataKey(moduleId),
    moduleId,
    kind: "project-usage",
    bytes,
    updatedAt: new Date().toISOString(),
  };
}

let fallbackSnapshotSequence = 0;

function createSnapshotId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return randomUuid;
  }
  fallbackSnapshotSequence += 1;
  return [
    Date.now().toString(36),
    fallbackSnapshotSequence.toString(36),
  ].join("-");
}

export class IndexedDbWorkshopProjectStorage
  implements ManagedWorkshopProjectStorage
{
  private readonly databasePromise: Promise<IDBDatabase>;
  private readonly limits: WorkshopProjectStorageLimits;

  constructor(
    factory: IDBFactory,
    databaseName = DEFAULT_DATABASE_NAME,
    options: Partial<WorkshopProjectStorageLimits> = {},
  ) {
    this.limits = normalizedLimits(options);
    this.databasePromise = this.open(factory, databaseName);
  }

  private open(
    factory: IDBFactory,
    databaseName: string,
  ): Promise<IDBDatabase> {
    return new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(databaseName, DATABASE_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        const transaction = request.transaction;
        const projectStore = database.objectStoreNames.contains(
          PROJECT_STORE,
        )
          ? transaction?.objectStore(PROJECT_STORE)
          : database.createObjectStore(PROJECT_STORE, {
              keyPath: "key",
            });
        if (
          projectStore &&
          !projectStore.indexNames.contains(UPDATED_AT_INDEX)
        ) {
          projectStore.createIndex(UPDATED_AT_INDEX, "updatedAt");
        }
        if (
          projectStore &&
          !projectStore.indexNames.contains(MODULE_ID_INDEX)
        ) {
          projectStore.createIndex(MODULE_ID_INDEX, "moduleId");
        }

        const snapshotStore = database.objectStoreNames.contains(
          SNAPSHOT_STORE,
        )
          ? transaction?.objectStore(SNAPSHOT_STORE)
          : database.createObjectStore(SNAPSHOT_STORE, {
              keyPath: "key",
            });
        if (
          snapshotStore &&
          !snapshotStore.indexNames.contains(MODULE_ID_INDEX)
        ) {
          snapshotStore.createIndex(MODULE_ID_INDEX, "moduleId");
        }
        if (!database.objectStoreNames.contains(METADATA_STORE)) {
          database.createObjectStore(METADATA_STORE, {
            keyPath: "key",
          });
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
      request.onerror = () =>
        reject(request.error ?? new Error("Unable to open IndexedDB."));
      request.onblocked = () =>
        reject(new Error("IndexedDB upgrade is blocked."));
    });
  }

  async save<TProject>(
    input: WorkshopProjectRecord<TProject>,
  ): Promise<void> {
    const prepared = preparedRecord(input, this.limits);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [PROJECT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    const store = transaction.objectStore(PROJECT_STORE);
    const projects = await readStoredProjectsForModule(
      store,
      prepared.record.moduleId,
    );
    const nextBytes =
      projects
        .filter(
          (project) =>
            project.key !==
            projectKey(
              prepared.record.moduleId,
              prepared.record.projectId,
            ),
        )
        .reduce(
          (total, project) =>
            total + estimateStoredBytes(withoutStorageKey(project)),
          0,
        ) + prepared.bytes;
    if (nextBytes > this.limits.moduleQuotaBytes) {
      await abortTransaction(transaction, completion);
      throw new WorkshopProjectStorageError(
        "project-quota-exceeded",
        "Workshop module project storage exceeds its quota.",
        this.limits.moduleQuotaBytes,
        nextBytes,
      );
    }
    store.put({
      ...prepared.record,
      key: projectKey(
        prepared.record.moduleId,
        prepared.record.projectId,
      ),
    } satisfies StoredWorkshopProject<TProject>);
    transaction
      .objectStore(METADATA_STORE)
      .put(usageMetadata(prepared.record.moduleId, nextBytes));
    await completion;
  }

  async load<TProject>(
    moduleId: string,
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(projectId, "projectId", 256);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      PROJECT_STORE,
      "readonly",
    );
    const completion = transactionComplete(transaction);
    const stored = await requestResult(
      transaction
        .objectStore(PROJECT_STORE)
        .get(projectKey(moduleId, projectId)),
    );
    await completion;
    return stored
      ? withoutStorageKey(
          stored as StoredWorkshopProject<TProject>,
        )
      : null;
  }

  async latest<TProject>(
    moduleId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      PROJECT_STORE,
      "readonly",
    );
    const completion = transactionComplete(transaction);
    const projects = await readStoredProjectsForModule(
      transaction.objectStore(PROJECT_STORE),
      moduleId,
    );
    await completion;
    projects.sort(
      (left, right) =>
        right.updatedAt.localeCompare(left.updatedAt) ||
        right.projectId.localeCompare(left.projectId),
    );
    return projects[0]
      ? withoutStorageKey(
          projects[0] as StoredWorkshopProject<TProject>,
        )
      : null;
  }

  async remove(moduleId: string, projectId: string): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(projectId, "projectId", 256);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [PROJECT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    const store = transaction.objectStore(PROJECT_STORE);
    const projects = await readStoredProjectsForModule(
      store,
      moduleId,
    );
    const key = projectKey(moduleId, projectId);
    const retained = projects.filter((project) => project.key !== key);
    store.delete(key);
    transaction
      .objectStore(METADATA_STORE)
      .put(
        usageMetadata(
          moduleId,
          projectBytes(retained.map(withoutStorageKey)),
        ),
      );
    await completion;
  }

  async snapshotModule(
    moduleId: string,
    version: string,
  ): Promise<string> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(version, "version", 128);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [PROJECT_STORE, SNAPSHOT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    const storedProjects = await readStoredProjectsForModule(
      transaction.objectStore(PROJECT_STORE),
      moduleId,
    );
    const projects = storedProjects.map((project) =>
      cloneValue(withoutStorageKey(project)),
    );
    const bytes = projectBytes(projects);
    const snapshotId = createSnapshotId();
    const snapshot: StoredWorkshopSnapshot = {
      key: snapshotKey(moduleId, snapshotId),
      moduleId,
      snapshotId,
      version,
      createdAt: new Date().toISOString(),
      projects,
      projectBytes: bytes,
    };
    transaction.objectStore(SNAPSHOT_STORE).put(snapshot);
    transaction.objectStore(METADATA_STORE).put({
      key: snapshotMetadataKey(moduleId, snapshotId),
      moduleId,
      kind: "snapshot",
      bytes,
      updatedAt: snapshot.createdAt,
    } satisfies StoredWorkshopMetadata);
    await completion;
    return snapshotId;
  }

  async restoreSnapshot(
    moduleId: string,
    snapshotId: string,
  ): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(snapshotId, "snapshotId", 256);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [PROJECT_STORE, SNAPSHOT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    const projectStore = transaction.objectStore(PROJECT_STORE);
    const snapshotRequest = requestResult(
      transaction
        .objectStore(SNAPSHOT_STORE)
        .get(snapshotKey(moduleId, snapshotId)),
    );
    const currentRequest = readStoredProjectsForModule(
      projectStore,
      moduleId,
    );
    const [rawSnapshot, current] = await Promise.all([
      snapshotRequest,
      currentRequest,
    ]);
    const snapshot = rawSnapshot as
      | StoredWorkshopSnapshot
      | undefined;
    if (!snapshot || snapshot.moduleId !== moduleId) {
      await abortTransaction(transaction, completion);
      throw new WorkshopProjectStorageError(
        "project-snapshot-not-found",
        "Workshop project snapshot was not found.",
      );
    }
    const restored = snapshot.projects.map((project) =>
      preparedRecord(project, this.limits),
    );
    const restoredBytes = restored.reduce(
      (total, prepared) => total + prepared.bytes,
      0,
    );
    if (restoredBytes > this.limits.moduleQuotaBytes) {
      await abortTransaction(transaction, completion);
      throw new WorkshopProjectStorageError(
        "project-quota-exceeded",
        "Workshop snapshot exceeds the current module quota.",
        this.limits.moduleQuotaBytes,
        restoredBytes,
      );
    }
    for (const project of current) {
      projectStore.delete(project.key);
    }
    for (const prepared of restored) {
      projectStore.put({
        ...prepared.record,
        key: projectKey(
          prepared.record.moduleId,
          prepared.record.projectId,
        ),
      } satisfies StoredWorkshopProject<unknown>);
    }
    transaction
      .objectStore(METADATA_STORE)
      .put(usageMetadata(moduleId, restoredBytes));
    await completion;
  }

  async deleteSnapshot(
    moduleId: string,
    snapshotId: string,
  ): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(snapshotId, "snapshotId", 256);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [SNAPSHOT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    transaction
      .objectStore(SNAPSHOT_STORE)
      .delete(snapshotKey(moduleId, snapshotId));
    transaction
      .objectStore(METADATA_STORE)
      .delete(snapshotMetadataKey(moduleId, snapshotId));
    await completion;
  }

  async deleteModuleProjects(moduleId: string): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    const database = await this.databasePromise;
    const transaction = database.transaction(
      [PROJECT_STORE, SNAPSHOT_STORE, METADATA_STORE],
      "readwrite",
    );
    const completion = transactionComplete(transaction);
    const projectStore = transaction.objectStore(PROJECT_STORE);
    const snapshotStore = transaction.objectStore(SNAPSHOT_STORE);
    const [projects, snapshots] = await Promise.all([
      readStoredProjectsForModule(projectStore, moduleId),
      readStoredSnapshotsForModule(snapshotStore, moduleId),
    ]);
    for (const project of projects) {
      projectStore.delete(project.key);
    }
    for (const snapshot of snapshots) {
      snapshotStore.delete(snapshot.key);
      transaction
        .objectStore(METADATA_STORE)
        .delete(snapshotMetadataKey(moduleId, snapshot.snapshotId));
    }
    transaction
      .objectStore(METADATA_STORE)
      .delete(usageMetadataKey(moduleId));
    await completion;
  }
}

function cloneRecord<TProject>(
  record: WorkshopProjectRecord<TProject>,
): WorkshopProjectRecord<TProject> {
  return cloneValue(record);
}

export class MemoryWorkshopProjectStorage
  implements ManagedWorkshopProjectStorage
{
  private readonly projects = new Map<
    string,
    WorkshopProjectRecord<unknown>
  >();
  private readonly snapshots = new Map<
    string,
    StoredWorkshopSnapshot
  >();
  private readonly limits: WorkshopProjectStorageLimits;

  constructor(
    options: Partial<WorkshopProjectStorageLimits> = {},
  ) {
    this.limits = normalizedLimits(options);
  }

  async save<TProject>(
    input: WorkshopProjectRecord<TProject>,
  ): Promise<void> {
    const prepared = preparedRecord(input, this.limits);
    const key = projectKey(
      prepared.record.moduleId,
      prepared.record.projectId,
    );
    const nextBytes =
      [...this.projects.entries()]
        .filter(
          ([candidateKey, project]) =>
            candidateKey !== key &&
            project.moduleId === prepared.record.moduleId,
        )
        .reduce(
          (total, [, project]) =>
            total + estimateStoredBytes(project),
          0,
        ) + prepared.bytes;
    if (nextBytes > this.limits.moduleQuotaBytes) {
      throw new WorkshopProjectStorageError(
        "project-quota-exceeded",
        "Workshop module project storage exceeds its quota.",
        this.limits.moduleQuotaBytes,
        nextBytes,
      );
    }
    this.projects.set(key, prepared.record);
  }

  async load<TProject>(
    moduleId: string,
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(projectId, "projectId", 256);
    const record = this.projects.get(projectKey(moduleId, projectId));
    return record
      ? cloneRecord(record as WorkshopProjectRecord<TProject>)
      : null;
  }

  async latest<TProject>(
    moduleId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    const records = [...this.projects.values()]
      .filter((record) => record.moduleId === moduleId)
      .sort(
        (left, right) =>
          right.updatedAt.localeCompare(left.updatedAt) ||
          right.projectId.localeCompare(left.projectId),
      );
    return records[0]
      ? cloneRecord(records[0] as WorkshopProjectRecord<TProject>)
      : null;
  }

  async remove(moduleId: string, projectId: string): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(projectId, "projectId", 256);
    this.projects.delete(projectKey(moduleId, projectId));
  }

  async snapshotModule(
    moduleId: string,
    version: string,
  ): Promise<string> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(version, "version", 128);
    const projects = [...this.projects.values()]
      .filter((project) => project.moduleId === moduleId)
      .map((project) => cloneRecord(project));
    const snapshotId = createSnapshotId();
    this.snapshots.set(snapshotKey(moduleId, snapshotId), {
      key: snapshotKey(moduleId, snapshotId),
      moduleId,
      snapshotId,
      version,
      createdAt: new Date().toISOString(),
      projects,
      projectBytes: projectBytes(projects),
    });
    return snapshotId;
  }

  async restoreSnapshot(
    moduleId: string,
    snapshotId: string,
  ): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(snapshotId, "snapshotId", 256);
    const snapshot = this.snapshots.get(
      snapshotKey(moduleId, snapshotId),
    );
    if (!snapshot) {
      throw new WorkshopProjectStorageError(
        "project-snapshot-not-found",
        "Workshop project snapshot was not found.",
      );
    }
    const restored = snapshot.projects.map((project) =>
      preparedRecord(project, this.limits),
    );
    const restoredBytes = restored.reduce(
      (total, prepared) => total + prepared.bytes,
      0,
    );
    if (restoredBytes > this.limits.moduleQuotaBytes) {
      throw new WorkshopProjectStorageError(
        "project-quota-exceeded",
        "Workshop snapshot exceeds the current module quota.",
        this.limits.moduleQuotaBytes,
        restoredBytes,
      );
    }
    const replacement = new Map<
      string,
      WorkshopProjectRecord<unknown>
    >();
    for (const prepared of restored) {
      replacement.set(
        projectKey(
          prepared.record.moduleId,
          prepared.record.projectId,
        ),
        prepared.record,
      );
    }
    for (const [key, project] of [...this.projects.entries()]) {
      if (project.moduleId === moduleId) {
        this.projects.delete(key);
      }
    }
    for (const [key, project] of replacement) {
      this.projects.set(key, project);
    }
  }

  async deleteSnapshot(
    moduleId: string,
    snapshotId: string,
  ): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    validateNamespaceValue(snapshotId, "snapshotId", 256);
    this.snapshots.delete(snapshotKey(moduleId, snapshotId));
  }

  async deleteModuleProjects(moduleId: string): Promise<void> {
    validateNamespaceValue(moduleId, "moduleId", 128);
    for (const [key, project] of [...this.projects.entries()]) {
      if (project.moduleId === moduleId) {
        this.projects.delete(key);
      }
    }
    for (const [key, snapshot] of [...this.snapshots.entries()]) {
      if (snapshot.moduleId === moduleId) {
        this.snapshots.delete(key);
      }
    }
  }
}

export function createWorkshopProjectStorage(
  factory: IDBFactory | null | undefined = globalThis.indexedDB,
  databaseName = DEFAULT_DATABASE_NAME,
  options: Partial<WorkshopProjectStorageLimits> = {},
): WorkshopProjectStorageResult {
  if (!factory) {
    return {
      storage: new MemoryWorkshopProjectStorage(options),
      persistent: false,
      status: "persistence-unavailable",
    };
  }
  return {
    storage: new IndexedDbWorkshopProjectStorage(
      factory,
      databaseName,
      options,
    ),
    persistent: true,
    status: "available",
  };
}
