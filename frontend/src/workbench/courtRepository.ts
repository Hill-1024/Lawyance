import { api, Item, remember, cached } from './client';
import { fileDB } from '../lib/db';
import type { CourtSession } from '../types';

/** Existing local trials stay local; project trials use revision-checked cloud snapshots. */
export class CourtRepository {
  private revisions = new Map<string, number>();
  private saved = new Map<string, string>();
  private queue: Promise<unknown> = Promise.resolve();
  private user = '';
  private ready = false;
  recovery: CourtSession[] = [];
  async load(): Promise<CourtSession[]> {
    const local = (await fileDB.getCourtSessions()).filter(s => !s.project_id);
    const status = await api('/status');
    if (!status.enabled) {this.ready = true; return local;}
    this.user = status.username;
    const courts = await api<Item[]>('/courts?include_session=true');
    const cloud = courts.map(item => {
      const session = {...item.data.session, auto_mode:false} as CourtSession;
      this.revisions.set(item.id, item.revision);
      this.saved.set(item.id, JSON.stringify(session));
      return session;
    });
    // Never silently replace a newer server copy with an offline snapshot.
    const pending = await cached<CourtSession[]>(this.user, 'court-unsaved') || [];
    this.recovery = pending.filter(s => cloud.some(c => c.id === s.id && JSON.stringify(c) !== JSON.stringify({...s,auto_mode:false})));
    this.ready = true;
    return [...pending.filter(s => !cloud.some(c => c.id === s.id)), ...cloud, ...local];
  }
  save(sessions: CourtSession[]): Promise<void> {
    const copies = structuredClone(sessions);
    const next = this.queue.catch(() => {}).then(async () => {
      if (!this.ready) return; // React cleanup may run before the initial read completes.
      if (this.recovery.length) throw new Error('存在未同步副本，请先导出恢复副本后刷新处理');
      await fileDB.saveCourtSessions(copies.filter(s => !s.project_id));
      const cloud = copies.filter(s => s.project_id);
      if (cloud.length && !this.user) throw new Error('云端庭审尚未连接，不能保存项目庭审');
      if (this.user) await remember(this.user, 'court-unsaved', cloud);
      const changed: Item[] = [];
      for (const session of cloud) {
        const snapshot = {...session, auto_mode:false};
        const fingerprint = JSON.stringify(snapshot);
        if (this.saved.get(session.id) === fingerprint) continue;
        const result = await api<Item>(`/courts/${session.id}/snapshot`, 'PUT', {
          project_id:session.project_id, expected_revision:this.revisions.get(session.id) || 0, session:snapshot,
        });
        changed.push({...result,data:{}});
        this.revisions.set(session.id, result.revision);
        this.saved.set(session.id, fingerprint);
      }
      if (this.user) await remember(this.user, 'court-unsaved', []);
      if(changed.length) window.dispatchEvent(new CustomEvent('lawver:courts-updated',{detail:{user:this.user,items:changed}}));
    });
    this.queue = next;
    return next;
  }
  async useCloudVersion() {
    this.recovery = [];
    if(this.user) await remember(this.user,'court-unsaved',[]);
  }
  async remove(id: string, project?: string) {
    await this.queue.catch(() => {});
    if (project) await api('/courts/' + id, 'DELETE');
    await fileDB.deleteCourtSession(id);
    this.saved.delete(id);
  }
}
