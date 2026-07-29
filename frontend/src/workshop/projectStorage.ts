import type {
  WorkshopProjectRecord,
  WorkshopProjectStorage,
} from "./types";

const DEFAULT_DATABASE_NAME = "lumina-workshop";
const DATABASE_VERSION = 1;
const PROJECT_STORE = "projects";
const UPDATED_AT_INDEX = "updatedAt";

interface StoredWorkshopProject<TProject = unknown>
  extends WorkshopProjectRecord<TProject> {
  key: string;
}

export interface WorkshopProjectStorageResult {
  storage: WorkshopProjectStorage;
  persistent: boolean;
  status: "available" | "persistence-unavailable";
}

function projectKey(moduleId: string, projectId: string): string {
  return `${moduleId}:${projectId}`;
}

function withoutStorageKey<TProject>(
  stored: StoredWorkshopProject<TProject>,
): WorkshopProjectRecord<TProject> {
  const { key: _key, ...record } = stored;
  return record;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new Error("IndexedDB request failed."));
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("IndexedDB transaction aborted."));
    transaction.onerror = () =>
      reject(transaction.error ?? new Error("IndexedDB transaction failed."));
  });
}

export class IndexedDbWorkshopProjectStorage
  implements WorkshopProjectStorage
{
  private readonly databasePromise: Promise<IDBDatabase>;

  constructor(
    factory: IDBFactory,
    databaseName = DEFAULT_DATABASE_NAME,
  ) {
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
        const store = database.objectStoreNames.contains(PROJECT_STORE)
          ? request.transaction?.objectStore(PROJECT_STORE)
          : database.createObjectStore(PROJECT_STORE, { keyPath: "key" });
        if (store && !store.indexNames.contains(UPDATED_AT_INDEX)) {
          store.createIndex(UPDATED_AT_INDEX, "updatedAt");
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () =>
        reject(request.error ?? new Error("Unable to open IndexedDB."));
      request.onblocked = () =>
        reject(new Error("IndexedDB upgrade is blocked."));
    });
  }

  async save<TProject>(
    record: WorkshopProjectRecord<TProject>,
  ): Promise<void> {
    const database = await this.databasePromise;
    const transaction = database.transaction(PROJECT_STORE, "readwrite");
    const completion = transactionComplete(transaction);
    transaction.objectStore(PROJECT_STORE).put({
      ...record,
      key: projectKey(record.moduleId, record.projectId),
    } satisfies StoredWorkshopProject<TProject>);
    await completion;
  }

  async load<TProject>(
    moduleId: string,
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    const database = await this.databasePromise;
    const transaction = database.transaction(PROJECT_STORE, "readonly");
    const completion = transactionComplete(transaction);
    const stored = await requestResult(
      transaction
        .objectStore(PROJECT_STORE)
        .get(projectKey(moduleId, projectId)),
    );
    await completion;
    return stored
      ? withoutStorageKey(stored as StoredWorkshopProject<TProject>)
      : null;
  }

  async latest<TProject>(
    moduleId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    const database = await this.databasePromise;
    const transaction = database.transaction(PROJECT_STORE, "readonly");
    const completion = transactionComplete(transaction);
    const index = transaction.objectStore(PROJECT_STORE).index(UPDATED_AT_INDEX);
    const stored = await new Promise<StoredWorkshopProject<TProject> | null>(
      (resolve, reject) => {
        const request = index.openCursor(null, "prev");
        request.onsuccess = () => {
          const cursor = request.result;
          if (!cursor) {
            resolve(null);
            return;
          }
          const candidate = cursor.value as StoredWorkshopProject<TProject>;
          if (candidate.moduleId === moduleId) {
            resolve(candidate);
            return;
          }
          cursor.continue();
        };
        request.onerror = () =>
          reject(request.error ?? new Error("IndexedDB cursor failed."));
      },
    );
    await completion;
    return stored ? withoutStorageKey(stored) : null;
  }

  async remove(moduleId: string, projectId: string): Promise<void> {
    const database = await this.databasePromise;
    const transaction = database.transaction(PROJECT_STORE, "readwrite");
    const completion = transactionComplete(transaction);
    transaction
      .objectStore(PROJECT_STORE)
      .delete(projectKey(moduleId, projectId));
    await completion;
  }
}

function cloneRecord<TProject>(
  record: WorkshopProjectRecord<TProject>,
): WorkshopProjectRecord<TProject> {
  return structuredClone(record);
}

export class MemoryWorkshopProjectStorage
  implements WorkshopProjectStorage
{
  private readonly projects = new Map<
    string,
    WorkshopProjectRecord<unknown>
  >();

  async save<TProject>(
    record: WorkshopProjectRecord<TProject>,
  ): Promise<void> {
    this.projects.set(
      projectKey(record.moduleId, record.projectId),
      cloneRecord(record),
    );
  }

  async load<TProject>(
    moduleId: string,
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
    const record = this.projects.get(projectKey(moduleId, projectId));
    return record
      ? cloneRecord(record as WorkshopProjectRecord<TProject>)
      : null;
  }

  async latest<TProject>(
    moduleId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null> {
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
    this.projects.delete(projectKey(moduleId, projectId));
  }
}

export function createWorkshopProjectStorage(
  factory: IDBFactory | null | undefined = globalThis.indexedDB,
  databaseName = DEFAULT_DATABASE_NAME,
): WorkshopProjectStorageResult {
  if (!factory) {
    return {
      storage: new MemoryWorkshopProjectStorage(),
      persistent: false,
      status: "persistence-unavailable",
    };
  }
  return {
    storage: new IndexedDbWorkshopProjectStorage(factory, databaseName),
    persistent: true,
    status: "available",
  };
}
