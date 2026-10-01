/*
 * 模块描述：credits 耗尽时的升级提示弹窗。仅对非 max/business、非运维豁免的账号、
 * 且余额归零时弹出；弹出节奏由 localStorage 冷却门控制——勾选「不再提醒」永久关闭，
 * 否则 14 天冷却一次，不高频打扰。「升级订阅」跳介绍页定价（同域跨进程真实跳转）。
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { CheckBox } from "../components/CheckBox";
import { useT } from "../i18n";

export function UpgradeNudge({ onClose }: { onClose: (options: { forever: boolean }) => void }) {
  const { t } = useT();
  const [never, setNever] = useState(false);

  return (
    <div
      className="wb-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose({ forever: never });
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose({ forever: never });
      }}
    >
      <section className="wb-nudge" role="dialog" aria-modal="true" aria-labelledby="wb-nudge-title">
        <span className="wb-nudge__mark" aria-hidden="true">
          <Sparkles size={20} strokeWidth={2} />
        </span>
        <h2 id="wb-nudge-title">{t("workbench.nudge.title")}</h2>
        <p className="wb-nudge__body">{t("workbench.nudge.body")}</p>
        <div className="wb-nudge__actions">
          <div className="wb-nudge__left">
            <CheckBox
              label={t("workbench.nudge.never")}
              checked={never}
              onCheckedChange={setNever}
            />
            <button
              type="button"
              className="wb-nudge__quiet"
              onClick={() => onClose({ forever: never })}
            >
              {t("workbench.nudge.again")}
            </button>
          </div>
          <a className="wb-nudge__upgrade" href="/pricing">
            {t("workbench.nudge.upgrade")}
          </a>
        </div>
      </section>
    </div>
  );
}
