import JSZip from 'jszip';
import { fileDB } from '../lib/db';

export const storageService = {
  async exportAllData() {
    const zip = new JSZip();
    
    // 1. Export Conversations
    const conversations = await fileDB.getConversations();
    zip.file('conversations.json', JSON.stringify(conversations, null, 2));
    
    // 2. Export Files
    const files = await fileDB.getAllFiles();
    const filesFolder = zip.folder('files');
    
    for (const file of files) {
      if (file.blob && file.blob.size > 0) {
        // Use id as filename to avoid collisions, or a descriptive name
        const fileName = `${file.convId}_${file.fileName}`;
        filesFolder?.file(fileName, file.blob);
      }
    }
    
    // 3. Generate Zip
    const content = await zip.generateAsync({ type: 'blob' });
    
    // 4. Trigger Download
    const url = URL.createObjectURL(content);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lawver_backup_${new Date().toISOString().split('T')[0]}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  async garbageCollect() {
    const files = await fileDB.getAllFiles();
    let cleanedCount = 0;
    let spaceSaved = 0;

    for (const file of files) {
      // Logic for "unimportant" data:
      // 1. Empty blobs
      // 2. Old logs or previews (if distinguishable)
      // For now, let's target very old files (> 30 days) that are not "upload" type if we had that info
      // Or just empty/invalid ones.
      
      if (!file.blob || file.blob.size === 0) {
        await fileDB.deleteFile(file.convId, file.fileName);
        cleanedCount++;
      }
    }
    
    return { cleanedCount, spaceSaved };
  },

  async clearOldData(daysThreshold: number = 30) {
    const conversations = await fileDB.getConversations();
    const now = Date.now();
    const threshold = daysThreshold * 24 * 60 * 60 * 1000;
    
    const oldConvs = conversations.filter(c => {
      // Find the latest message timestamp
      const lastMsg = c.messages[c.messages.length - 1];
      const ts = lastMsg ? (parseInt(lastMsg.id) || now) : now; 
      return (now - ts) > threshold;
    });

    for (const conv of oldConvs) {
      await fileDB.deleteFilesByConvId(conv.id);
    }
    
    // Update conversations list
    const remainingConvs = conversations.filter(c => !oldConvs.find(oc => oc.id === c.id));
    await fileDB.saveConversations(remainingConvs);
    
    return oldConvs.length;
  },

  // --- Dialogue Migration (Text Only) ---

  async _getKey() {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      "raw",
      enc.encode("GDUT-Lawyer-Security-Migration-Key-2024"),
      "PBKDF2",
      false,
      ["deriveBits", "deriveKey"]
    );
    return crypto.subtle.deriveKey(
      {
        name: "PBKDF2",
        salt: enc.encode("GDUT-Lawyer-Salt"),
        iterations: 100000,
        hash: "SHA-256",
      },
      keyMaterial,
      { name: "AES-GCM", length: 256 },
      true,
      ["encrypt", "decrypt"]
    );
  },

  async encryptData(data: string) {
    const key = await this._getKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(data);
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      encoded
    );
    
    // Combine IV and Encrypted Data
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);
    
    return btoa(String.fromCharCode(...combined));
  },

  async decryptData(base64: string) {
    const key = await this._getKey();
    const combined = new Uint8Array(atob(base64).split('').map(c => c.charCodeAt(0)));
    const iv = combined.slice(0, 12);
    const data = combined.slice(12);
    
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      key,
      data
    );
    
    return new TextDecoder().decode(decrypted);
  },

  async exportConversationsText() {
    const conversations = await fileDB.getConversations();
    // Strip everything but text data to be safe, though Conversation type is already clean
    const data = JSON.stringify(conversations);
    const encrypted = await this.encryptData(data);
    
    const blob = new Blob([encrypted], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lawyer_dialogues_${new Date().toISOString().split('T')[0]}.lawyer`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  async importConversationsFromFile(file: File) {
    const text = await file.text();
    const decrypted = await this.decryptData(text);
    const conversations = JSON.parse(decrypted) as any[];
    
    const newConversations = conversations.map(conv => {
      const oldId = conv.id;
      const newId = crypto.randomUUID();
      
      // Update Conversation ID
      const newConv = { ...conv, id: newId };
      
      // Update Message contents and reasoning_content (replace oldId with newId)
      newConv.messages = conv.messages.map((msg: any) => {
        let content = msg.content || '';
        let reasoning_content = msg.reasoning_content || '';
        
        if (content.includes(oldId)) {
          content = content.replaceAll(oldId, newId);
        }
        if (reasoning_content.includes(oldId)) {
          reasoning_content = reasoning_content.replaceAll(oldId, newId);
        }
        
        return { ...msg, content, reasoning_content };
      });
      
      return newConv;
    });
    
    await fileDB.addConversations(newConversations);
    return newConversations.length;
  }
};
