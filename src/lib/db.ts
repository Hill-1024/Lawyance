/*
 * 模块描述：IndexedDB 数据访问层，持久化会话、上传文件和生成文件元数据。
 */

import { Conversation } from '../types';

export class FileDB {
  private dbName = 'LawyanceFileDB';
  private previousDbNames = [
    this.decodeName([76, 97, 119, 118, 101, 114]) + 'FileDB',
    this.decodeName([76, 97, 119, 121, 101, 114]) + 'FileDB'
  ];
  private storeName = 'files';
  private convStoreName = 'conversations';
  private version = 2; // Incremented version to add store
  private migrationPromise: Promise<void> | null = null;

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

  private async getDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.version);
      request.onerror = () => reject(request.error);
      request.onsuccess = async () => {
        const db = request.result;
        try {
          await this.ensurePreviousDataMigrated(db);
        } catch (error) {
          console.warn('Lawyance IndexedDB migration skipped:', error);
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
      };
    });
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
    const db = await this.getDB();
    const id = this.buildFileId(convId, fileName, path);
    return new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.put({ id, convId, fileName, blob, path: path || '', timestamp: Date.now() });
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  }

  async getFilesByConvId(convId: string): Promise<{fileName: string, blob: Blob, path: string, id: string}[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
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
    });
  }

  async getAllFiles(): Promise<any[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readonly');
      const store = transaction.objectStore(this.storeName);
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async deleteFilesByConvId(convId: string) {
    const db = await this.getDB();
    return new Promise<void>((resolve, reject) => {
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
    });
  }

  async deleteFile(convId: string, fileName: string, path?: string) {
    const db = await this.getDB();
    return new Promise<void>((resolve, reject) => {
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
    });
  }

  // --- Conversation Methods ---

  async saveConversations(conversations: Conversation[]) {
    const db = await this.getDB();
    return new Promise<void>((resolve, reject) => {
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
    });
  }

  async addConversations(conversations: Conversation[]) {
    const db = await this.getDB();
    return new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readwrite');
      const store = transaction.objectStore(this.convStoreName);
      
      conversations.forEach(conv => store.put(conv));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  }

  async getConversations(): Promise<Conversation[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
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
    });
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
