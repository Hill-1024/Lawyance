
export class FileDB {
  private dbName = 'LawverFileDB';
  private storeName = 'files';
  private version = 1;

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
      };
    });
  }

  async saveFile(convId: string, fileName: string, blob: Blob, path: string) {
    const db = await this.getDB();
    const id = `${convId}_${fileName}`;
    return new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.put({ id, convId, fileName, blob, path, timestamp: Date.now() });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async getFilesByConvId(convId: string): Promise<{fileName: string, blob: Blob, path: string}[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(this.storeName, 'readonly');
      const store = transaction.objectStore(this.storeName);
      const request = store.getAll();
      request.onsuccess = () => {
        const all = request.result as any[];
        resolve(all.filter(f => f.convId === convId).map(f => ({
          fileName: f.fileName,
          blob: f.blob,
          path: f.path
        })));
      };
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
}

export const fileDB = new FileDB();
