import React from "react";
import { useParams } from "react-router-dom";
import { apiUrl } from "../services/api";
import { useT } from "../i18n";
import { APP_CONFIG } from "../lib/app-config";
import { Markdown } from "./markdown";
import "./sharing.css";

type Snapshot = { title: string; expires_at: string; messages: { role: "user" | "assistant"; content: string }[] };

export default function SharedConversation() {
  const { token } = useParams();
  const { t } = useT();
  const [snapshot, setSnapshot] = React.useState<Snapshot>();
  const [unavailable, setUnavailable] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const [retry, setRetry] = React.useState(0);

  React.useEffect(() => {
    const tags = [["robots", "noindex, nofollow, noarchive"], ["referrer", "no-referrer"]].map(([name, content]) => {
      const tag = document.createElement("meta");
      tag.name = name; tag.content = content; document.head.appendChild(tag);
      return tag;
    });
    return () => tags.forEach((tag) => tag.remove());
  }, []);

  React.useEffect(() => {
    const controller = new AbortController();
    let redirect: ReturnType<typeof setTimeout> | undefined;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    let pending = false;
    let loaded = false;
    let gone = false;
    const expire = () => {
      if (gone || controller.signal.aborted) return;
      gone = true;
      setSnapshot(undefined); setUnavailable(true); setFailed(false);
      redirect = setTimeout(() => window.location.replace(`${APP_CONFIG.origin}/`), 3000);
    };
    const load = async () => {
      if (pending || gone || controller.signal.aborted || document.visibilityState === "hidden") return;
      pending = true;
      // Bound request time so a stalled connection cannot leave stale shared text visible forever.
      const timeout = new AbortController();
      const cancel = () => timeout.abort();
      controller.signal.addEventListener("abort", cancel, { once: true });
      const deadline = setTimeout(cancel, 10000);
      try {
        const path = `/api/shares/${encodeURIComponent(token || "")}${loaded ? "/status" : ""}`;
        const response = await fetch(apiUrl(path), { signal: timeout.signal, credentials: "omit", cache: "no-store" });
        if (controller.signal.aborted || gone) return;
        if ([404, 410, 422].includes(response.status)) { expire(); return; }
        if (!response.ok) throw new Error("Share unavailable");
        const value: Snapshot = await response.json();
        if (controller.signal.aborted || gone) return;
        if (!loaded) setSnapshot(value);
        loaded = true; setFailed(false);
        clearTimeout(expiry);
        // Recheck the deadline when a 30-day share exceeds the browser's maximum timeout.
        const checkExpiry = () => {
          const remaining = Date.parse(value.expires_at) - Date.now();
          if (remaining <= 0) { expire(); return; }
          expiry = setTimeout(checkExpiry, Math.min(2147483647, remaining));
        };
        checkExpiry();
      } catch {
        if (!controller.signal.aborted && !gone) { setSnapshot(undefined); setFailed(true); loaded = false; }
      } finally {
        clearTimeout(deadline); controller.signal.removeEventListener("abort", cancel); pending = false;
      }
    };
    void load();
    const poll = setInterval(() => void load(), 15000);
    const visibility = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener("focus", load);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      controller.abort(); clearInterval(poll); clearTimeout(redirect); clearTimeout(expiry);
      window.removeEventListener("focus", load); document.removeEventListener("visibilitychange", visibility);
    };
  }, [token, retry]);

  return <main className="shared-conversation"><div className="shared-paper">
    <p>{t("sharing.readOnly")}</p>
    {unavailable ? <div role="status"><p>{t("sharing.unavailable")}</p><a href={`${APP_CONFIG.origin}/`}>{t("sharing.back")}</a></div>
      : failed ? <div role="alert"><p>{t("sharing.loadError")}</p><button onClick={() => setRetry((n) => n + 1)}>{t("common.retry")}</button></div>
      : snapshot ? <><h1>{snapshot.title}</h1><p>{t("sharing.expires", { date: new Date(snapshot.expires_at).toLocaleString() })}</p>
        {snapshot.messages.map((message, index) => <article key={index}>
          <strong>{t(message.role === "user" ? "sharing.user" : "sharing.assistant")}</strong>
          <Markdown publicShare>{message.content}</Markdown>
        </article>)}</> : <p role="status">{t("sharing.loading")}</p>}
  </div></main>;
}
