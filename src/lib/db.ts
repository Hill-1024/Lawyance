import { Conversation } from '../types';

export class FileDB {
  private dbName = 'LawyerFileDB';
  private storeName = 'files';
  private convStoreName = 'conversations';
  private version = 2; // Incremented version to add store

  private async getDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.version);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
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

  // --- File Methods ---

  async saveFile(convId: string, fileName: string, blob: Blob, path: string) {
    const db = await this.getDB();
    const id = `${convId}_${fileName}`;
    return new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.put({ id, convId, fileName, blob, path: path || '', timestamp: Date.now() });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
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
    const transaction = db.transaction(this.storeName, 'readwrite');
    const store = transaction.objectStore(this.storeName);
    const request = store.getAll();
    request.onsuccess = () => {
      const targets = (request.result as any[]).filter(f => f.convId === convId);
      targets.forEach(t => store.delete(t.id));
    };
  }

  async deleteFile(convId: string, fileName: string) {
    const db = await this.getDB();
    const id = `${convId}_${fileName}`;
    const transaction = db.transaction(this.storeName, 'readwrite');
    const store = transaction.objectStore(this.storeName);
    return new Promise<void>((resolve, reject) => {
      const request = store.delete(id);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  // --- Conversation Methods ---

  async saveConversations(conversations: Conversation[]) {
    const db = await this.getDB();
    return new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readwrite');
      const store = transaction.objectStore(this.convStoreName);
      
      const clearReq = store.clear();
      clearReq.onsuccess = () => {
        conversations.forEach(conv => store.put(conv));
        resolve();
      };
      clearReq.onerror = () => reject(clearReq.error);
    });
  }

  async getConversations(): Promise<Conversation[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(this.convStoreName, 'readonly');
      const store = transaction.objectStore(this.convStoreName);
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result);
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
