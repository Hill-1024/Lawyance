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
  }
};
