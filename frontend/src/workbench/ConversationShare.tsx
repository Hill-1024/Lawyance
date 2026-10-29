import React from "react";
import { ClockAlert, FileDown, Link2, Share2, X } from "lucide-react";
import { api, Conflict } from "./client";
import { useT } from "../i18n";
import { APP_CONFIG, BASE_PATH } from "../lib/app-config";
import { isNative } from "../lib/platform";
import { describeError } from "../lib/errors";
import { downloadApiFile } from "../lib/download";
import "./sharing.css";

type ShareState = {
  status: "not_created" | "active" | "expired" | "revoked";
  token?: string;
  path?: string | null;
  expires_at?: string;
};

export function ConversationShare({ id, title, blocked, offline }: {
  id: string; title: string; blocked: boolean; offline: boolean;
}) {
  const { t } = useT();
  const [share, setShare] = React.useState<ShareState>();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [days, setDays] = React.useState(30);
  const [clock, setClock] = React.useState(Date.now());
  const dialog = React.useRef<HTMLDialogElement>(null);
  const mounted = React.useRef(true);
  const pending = React.useRef(false);
  const sequence = React.useRef(0);
  const createRequest = React.useRef<{ key: string; days: number } | null>(null);
  const base = `/conversations/${encodeURIComponent(id)}/share`;

  const refresh = React.useCallback(async () => {
    const request = ++sequence.current;
    try {
      const value = await api<ShareState>(base);
      if (mounted.current && request === sequence.current) {
        setShare(value); setClock(Date.now());
      }
    } catch (e) {
      if (mounted.current && request === sequence.current) setError(describeError(e));
    }
  }, [base]);

  React.useEffect(() => {
    mounted.current = true;
    sequence.current++;
    const reload = () => {
      if (!offline && !pending.current && document.visibilityState !== "hidden") void refresh();
    };
    reload();
    const timer = setInterval(() => { setClock(Date.now()); reload(); }, 30000);
    window.addEventListener("focus", reload);
    return () => {
      mounted.current = false;
      clearInterval(timer); window.removeEventListener("focus", reload);
    };
  }, [refresh, offline]);

  React.useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);

  const active = share?.status === "active" && Date.parse(share.expires_at || "") > clock;
  const shareUrl = active && share?.path
    ? `${isNative() ? APP_CONFIG.origin : window.location.origin}${BASE_PATH}${share.path}` : "";
  const stateText = !share ? t("sharing.loading") : share.status === "not_created"
    ? t("sharing.notCreated") : active
      ? t("sharing.expires", { date: new Date(share.expires_at!).toLocaleString() })
      : share.status === "revoked" ? t("sharing.revoked") : t("sharing.expired");

  const perform = async (action: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true; sequence.current++;
    setBusy(true); setError(""); setCopied(false);
    try { await action(); }
    catch (e) {
      if (mounted.current) {
        setError(describeError(e));
        if (e instanceof Conflict && e.status === 409) await refresh();
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const create = () => perform(async () => {
    if (!createRequest.current || createRequest.current.days !== days) {
      createRequest.current = { days, key: crypto.randomUUID() };
    }
    try {
      const value = await api<ShareState>(base, "POST", { days }, createRequest.current.key);
      createRequest.current = null;
      if (mounted.current) { setShare(value); setClock(Date.now()); }
    } catch (e) {
      if (e instanceof Conflict && e.status && e.status < 500) createRequest.current = null;
      throw e;
    }
  });
  const revoke = () => perform(async () => {
    const value = await api<ShareState>(`${base}/${share!.token}`, "DELETE");
    createRequest.current = null;
    if (mounted.current) setShare(value);
  });
  const exportWord = () => perform(async () => {
    await downloadApiFile(`/api/workbench/conversations/${encodeURIComponent(id)}/export`,
      (title || t("workbench.session.untitled")) + ".docx");
  });

  return <>
    <button className="wb-thread-tool" aria-label={t("sharing.title")} title={t("sharing.title")}
      onClick={() => { setOpen(true); setCopied(false); if (!offline && !pending.current) void refresh(); }}>
      <Share2 size={16} />
      {active && <Link2 size={13} aria-label={t("sharing.active")} />}
      {share && share.status !== "not_created" && !active && <ClockAlert size={13} aria-label={stateText} />}
    </button>
    <dialog ref={dialog} className="conversation-share" aria-labelledby={`share-title-${id}`}
      onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>
      <header><h2 id={`share-title-${id}`}>{t("sharing.title")}</h2>
        <button aria-label={t("sharing.close")} onClick={() => setOpen(false)}><X size={18} /></button></header>
      <section><h3><FileDown size={18} />{t("sharing.wordTitle")}</h3>
        <p>{t("sharing.wordHint")}</p>
        <button disabled={busy || blocked || offline} onClick={() => void exportWord()}>{t("workbench.session.exportWord")}</button>
      </section>
      <section><h3><Link2 size={18} />{t("sharing.urlTitle")}</h3>
        <p>{t("sharing.snapshotHint")}</p><p role="status">{stateText}</p>
        {active ? <>
          <input aria-label={t("sharing.urlTitle")} readOnly value={shareUrl} onFocus={(e) => e.currentTarget.select()} />
          <div className="share-actions">
            <button disabled={busy} onClick={() => void perform(async () => {
              await navigator.clipboard.writeText(shareUrl);
              if (mounted.current) setCopied(true);
            })}>{copied ? t("sharing.copied") : t("sharing.copy")}</button>
            <button disabled={busy || offline} onClick={() => void revoke()}>{t("sharing.revoke")}</button>
          </div>
        </> : <>
          <label>{t("sharing.validity")} <select value={days} disabled={busy} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 21, 30].map((n) => <option key={n} value={n}>{t("sharing.days", { count: n })}</option>)}
          </select></label>
          <button disabled={busy || blocked || offline || !share} onClick={() => void create()}>{t("sharing.create")}</button>
        </>}
      </section>
      {busy && <p role="status">{t("sharing.working")}</p>}
      {error && <div role="alert"><p>{error}</p><button disabled={busy || offline} onClick={() => { setError(""); void refresh(); }}>{t("common.retry")}</button></div>}
      {(blocked || offline) && <p>{t("sharing.disabled")}</p>}
    </dialog>
  </>;
}
