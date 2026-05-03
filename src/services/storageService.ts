import JSZip from 'jszip/dist/jszip.min.js';
import { fileDB } from '../lib/db';

export const storageService = {

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
        await fileDB.deleteFile(file.convId, file.fileName, file.path);
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

  async encryptDataToBlob(data: string): Promise<Blob> {
    // 使用简单的异或加密（混淆）来防止明文泄露，并避免因为 IP 访问（非 HTTPS 环境）导致 crypto.subtle 无法使用的问题。
    // 同时使用 Blob 直接生成文件，避免超大文本使用 String.fromCharCode 导致栈溢出。
    const key = "GDUT-Lawyer-Security-Migration-Key-2024";
    const encoded = new TextEncoder().encode(data);
    for (let i = 0; i < encoded.length; i++) {
      encoded[i] = encoded[i] ^ key.charCodeAt(i % key.length);
    }
    return new Blob([encoded], { type: 'application/octet-stream' });
  },

  async decryptDataFromFile(file: File): Promise<string> {
    const arrayBuffer = await file.arrayBuffer();
    const bytes = new Uint8Array(arrayBuffer);
    const key = "GDUT-Lawyer-Security-Migration-Key-2024";
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = bytes[i] ^ key.charCodeAt(i % key.length);
    }
    return new TextDecoder().decode(bytes);
  },

  async exportConversationsText() {
    const conversations = await fileDB.getConversations();
    // Strip everything but text data to be safe, though Conversation type is already clean
    const data = JSON.stringify(conversations);
    const blob = await this.encryptDataToBlob(data);
    
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
    const decrypted = await this.decryptDataFromFile(file);
    const conversations = JSON.parse(decrypted) as any[];
    
    const newConversations = conversations.map(conv => {
      const oldId = conv.id;
      const newId = crypto.randomUUID();
      
      // Update Conversation ID
      const newConv = { ...conv, id: newId };
      if (newConv.memory) {
        newConv.memory = {
          ...newConv.memory,
          conversation_id: newId,
          last_synced_at: '',
          updated_at: new Date().toISOString()
        };
      }
      
      // Update Message contents and structured thought blocks (replace oldId with newId)
      newConv.messages = conv.messages.map((msg: any) => {
        let content = msg.content || '';
        let reasoning_content = msg.reasoning_content || '';
        const thought_blocks = Array.isArray(msg.thought_blocks)
          ? msg.thought_blocks.map((block: any) => ({
              ...block,
              content: typeof block.content === 'string' ? block.content.replaceAll(oldId, newId) : block.content
            }))
          : msg.thought_blocks;
        
        if (content.includes(oldId)) {
          content = content.replaceAll(oldId, newId);
        }
        if (reasoning_content.includes(oldId)) {
          reasoning_content = reasoning_content.replaceAll(oldId, newId);
        }
        
        return { ...msg, content, reasoning_content, thought_blocks };
      });
      
      return newConv;
    });
    
    await fileDB.addConversations(newConversations);
    return newConversations.length;
  }
};
