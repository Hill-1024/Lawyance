/*
 * 模块描述：IndexedDB 数据访问层，持久化会话、上传文件和生成文件元数据。
 */

import { Conversation, CourtSession } from '../types';
import { normalizeWorkspacePath } from './workspace-path';

class FileDB {
  private dbName = 'LawverFileDB';
  private previousDbNames = [
    this.decodeName([76, 97, 119, 118, 101, 114]) + 'FileDB',
    this.decodeName([76, 97, 119, 121, 101, 114]) + 'FileDB'
  ];
  private storeName = 'files';
  private convStoreName = 'conversations';
  private courtStoreName = 'court_sessions';
  private version = 3; // Incremented version to add court session store
  private migrationPromise: Promise<void> | null = null;
  private dbPromise: Promise<IDBDatabase> | null = null;
  private activeDb: IDBDatabase | null = null;

  private buildFileId(convId: string, fileName: string, path?: string) {
    return `${convId}::${path || fileName}`;
  }

  private decodeName(codes: number[]): string {
    return codes.map(code => String.fromCharCode(code)).join('');
  }

  private conversationTimestamp(conv: Conversation): number {
    const candidates = [
      Date.parse(conv.updated_at || ''),
      Date.parse(conv.created_at || ''),
      ...conv.messages.map(msg => {
        const explicit = Date.parse(msg.updated_at || msg.created_at || '');
        if (!Number.isNaN(explicit)) return explicit;
        const numericId = Number(msg.id);
        return Number.isFinite(numericId) ? numericId : 0;
      })
    ];
    return Math.max(...candidates.filter(value => Number.isFinite(value)), 0);
  }

  private courtSessionTimestamp(session: CourtSession): number {
    const candidates = [
      Date.parse(session.updated_at || ''),
      Date.parse(session.created_at || ''),
      ...(session.public_events || []).map(event => {
        const explicit = Date.parse(event.updated_at || event.created_at || '');
        return Number.isNaN(explicit) ? 0 : explicit;
      })
    ];
    return Math.max(...candidates.filter(value => Number.isFinite(value)), 0);
  }

  /** 浏览器空闲/后台回收后会关掉 IDB；缓存句柄必须一并丢弃。 */
  private forgetConnection(db?: IDBDatabase | null) {
    if (db && this.activeDb && this.activeDb !== db) {
      return;
    }
    this.activeDb = null;
    this.dbPromise = null;
  }

  private isConnectionError(error: unknown): boolean {
    const message = String((error as Error)?.message || error || '');
    return /InvalidStateError|database connection is closing|connection is closing|database connection is closed|Connection to Indexed Database server lost/i.test(
      message
    ) || (error as DOMException)?.name === 'InvalidStateError';
  }

  private async withDB<T>(operation: (db: IDBDatabase) => Promise<T>): Promise<T> {
    try {
      return await operation(await this.getDB());
    } catch (error) {
      if (!this.isConnectionError(error)) {
        throw error;
      }
      this.forgetConnection(this.activeDb);
      return await operation(await this.getDB());
    }
  }

  private async getDB(): Promise<IDBDatabase> {
    if (this.activeDb) {
      return this.activeDb;
    }
    if (this.dbPromise) {
      return this.dbPromise;
    }

    this.dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.version);
      request.onerror = () => {
        this.forgetConnection();
        reject(request.error);
      };
      request.onsuccess = async () => {
        const db = request.result;
        this.activeDb = db;
        // 正常 close() 不一定触发 onclose，versionchange 里仍需主动清理。
        db.onversionchange = () => {
          try {
            db.close();
          } catch {
            /* ignore */
          }
          this.forgetConnection(db);
        };
        db.onclose = () => {
          this.forgetConnection(db);
        };
        try {
          await this.ensurePreviousDataMigrated(db);
        } catch (error) {
          console.warn('Lawver IndexedDB migration skipped:', error);
        }
        resolve(db);
      };
      request.onupgradeneeded = (e) => {
        const db = (e.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(this.storeName)) {
          db.createObjectStore(this.storeName, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(this.convStoreName)) {
          db.createObjectStore(this.convStoreName, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(this.courtStoreName)) {
          db.createObjectStore(this.courtStoreName, { keyPath: 'id' });
        }
      };
      request.onblocked = () => {
        console.warn('Lawver IndexedDB open blocked; close other tabs using the same origin DB');
      };
    });

    try {
      return await this.dbPromise;
    } catch (error) {
      this.forgetConnection();
      throw error;
    }
  }

  private async ensurePreviousDataMigrated(db: IDBDatabase): Promise<void> {
    if (!this.migrationPromise) {
      this.migrationPromise = this.migratePreviousData(db);
    }
    await this.migrationPromise;
  }

  private async migratePreviousData(targetDb: IDBDatabase): Promise<void> {
    const databases = await indexedDB.databases?.();
    const previousDbName = databases
      ?.map(database => database.name)
      .find((name): name is string => Boolean(name && this.previousDbNames.includes(name)));
    if (!previousDbName) {
      return;
    }

    const [currentFiles, currentConversations] = await Promise.all([
      this.readAllFromDB(targetDb, this.storeName),
      this.readAllFromDB(targetDb, this.convStoreName)
    ]);
    if (currentFiles.length || currentConversations.length) {
      return;
    }

    const previousDb = await this.openDB(previousDbName);
    try {
      const [files, conversations] = await Promise.all([
        this.readAllFromDB(previousDb, this.storeName),
        this.readAllFromDB(previousDb, this.convStoreName)
      ]);
      await Promise.all([
        this.writeAllToDB(targetDb, this.storeName, files),
        this.writeAllToDB(targetDb, this.convStoreName, conversations)
      ]);
    } finally {
      previousDb.close();
    }
  }

  private async openDB(name: string): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
    });
  }

  private async readAllFromDB<T = any>(db: IDBDatabase, storeName: string): Promise<T[]> {
    if (!db.objectStoreNames.contains(storeName)) {
      return [];
    }
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readonly');
      const store = transaction.objectStore(storeName);
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result as T[]);
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    });
  }

  private async writeAllToDB(db: IDBDatabase, storeName: string, records: any[]): Promise<void> {
    if (!records.length || !db.objectStoreNames.contains(storeName)) {
      return;
    }
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite');
      const store = transaction.objectStore(storeName);
      records.forEach(record => store.put(record));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  }

  // --- File Methods ---

  async saveFile(convId: string, fileName: string, blob: Blob, path: string) {
    // 主键含路径，必须先把路径归一成 TEMP/… 相对形式：否则同一个文件一次以
    // 绝对路径写入、一次以相对路径写入会留下两条记录，界面上看起来是两份。
    const normalizedPath = normalizeWorkspacePath(path);
    const id = this.buildFileId(convId, fileName, normalizedPath);
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.put({ id, convId, fileName, blob, path: normalizedPath, timestamp: Date.now() });
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async getFilesByConvId(convId: string): Promise<{fileName: string, blob: Blob, path: string, id: string}[]> {
    return this.withDB(db => new Promise((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readonly');
      const store = transaction.objectStore(this.storeName);
      const request = store.getAll();
      request.onsuccess = () => {
        const all = request.result as any[];
        resolve(all.filter(f => f.convId === convId).map(f => ({
          id: f.id,
          fileName: f.fileName,
          blob: f.blob,
          path: f.path
        })));
      };
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async getAllFiles(): Promise<any[]> {
    return this.withDB(db => new Promise((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readonly');
      const store = transaction.objectStore(this.storeName);
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async deleteFilesByConvId(convId: string) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.getAll();
      request.onsuccess = () => {
        const targets = (request.result as any[]).filter(f => f.convId === convId);
        targets.forEach(t => store.delete(t.id));
      };
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async deleteFile(convId: string, fileName: string, path?: string) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);

      if (path) {
        const request = store.delete(this.buildFileId(convId, fileName, path));
        request.onerror = () => reject(request.error);
      } else {
        const request = store.getAll();
        request.onsuccess = () => {
          const targets = (request.result as any[]).filter(f => f.convId === convId && f.fileName === fileName);
          targets.forEach(t => store.delete(t.id));
        };
        request.onerror = () => reject(request.error);
      }

      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  // --- Conversation Methods ---

  async saveConversations(conversations: Conversation[]) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readwrite');
      const store = transaction.objectStore(this.convStoreName);

      const keysReq = store.getAllKeys();
      keysReq.onsuccess = () => {
        const incomingIds = new Set(conversations.map(conv => conv.id));
        (keysReq.result as IDBValidKey[]).forEach(key => {
          if (!incomingIds.has(String(key))) {
            store.delete(key);
          }
        });
        conversations.forEach(conv => store.put(conv));
      };
      keysReq.onerror = () => reject(keysReq.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async addConversations(conversations: Conversation[]) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readwrite');
      const store = transaction.objectStore(this.convStoreName);
      
      conversations.forEach(conv => store.put(conv));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async getConversations(): Promise<Conversation[]> {
    return this.withDB(db => new Promise((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readonly');
      const store = transaction.objectStore(this.convStoreName);
      const request = store.getAll();
      request.onsuccess = () => {
        const conversations = (request.result as Conversation[])
          .slice()
          .sort((a, b) => this.conversationTimestamp(b) - this.conversationTimestamp(a));
        resolve(conversations);
      };
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  // --- Court Session Methods ---

  async saveCourtSessions(courtSessions: CourtSession[]) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.courtStoreName, 'readwrite');
      const store = transaction.objectStore(this.courtStoreName);

      const keysReq = store.getAllKeys();
      keysReq.onsuccess = () => {
        const incomingIds = new Set(courtSessions.map(session => session.id));
        (keysReq.result as IDBValidKey[]).forEach(key => {
          if (!incomingIds.has(String(key))) {
            store.delete(key);
          }
        });
        courtSessions.forEach(session => store.put(session));
      };
      keysReq.onerror = () => reject(keysReq.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async addCourtSessions(courtSessions: CourtSession[]) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.courtStoreName, 'readwrite');
      const store = transaction.objectStore(this.courtStoreName);

      courtSessions.forEach(session => store.put(session));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async getCourtSessions(): Promise<CourtSession[]> {
    return this.withDB(db => new Promise((resolve, reject) => {
      const transaction = db.transaction(this.courtStoreName, 'readonly');
      const store = transaction.objectStore(this.courtStoreName);
      const request = store.getAll();
      request.onsuccess = () => {
        const courtSessions = (request.result as CourtSession[])
          .slice()
          .sort((a, b) => this.courtSessionTimestamp(b) - this.courtSessionTimestamp(a));
        resolve(courtSessions);
      };
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  async deleteCourtSession(id: string) {
    return this.withDB(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.courtStoreName, 'readwrite');
      const store = transaction.objectStore(this.courtStoreName);
      const request = store.delete(id);
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    }));
  }

  // --- Storage Utils ---

  async getEstimate() {
    if (navigator.storage && navigator.storage.estimate) {
      return await navigator.storage.estimate();
    }
    return { usage: 0, quota: 0 };
  }
}

export const fileDB = new FileDB();
