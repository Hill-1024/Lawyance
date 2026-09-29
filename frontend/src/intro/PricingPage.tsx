/*
 * 模块描述：定价页。套餐目录来自后端 /api/plans（不在前端硬编码价格），
 * 支付未开放：每张卡底部「订阅」打开客服二维码弹窗，由客服一对一开通。
 * 视觉沿用介绍页语言（.section / .download-card / .highlight-card）。
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Check, MessageCircle, X } from "lucide-react";
import "./intro-pricing.css";

interface Plan {
  id: string;
  name: string;
  tagline: string;
  price_month: number | null;
  price_year: number | null;
  monthly_credits: number | null;
  multiplier: number;
  max_online: number | null;
  recommended?: boolean;
  highlights: string[];
}

/** 客服群二维码：占位阶段用内联渲染，拿到真实二维码后把 KEFU_QR_IMAGE 指向图片即可。 */
const KEFU_QR_IMAGE: string | null = null;

const FALLBACK_PLANS: Plan[] = [
  {
    id: "metered",
    name: "按量充值",
    tagline: "不订阅，用多少付多少",
    price_month: 0,
    price_year: 0,
    monthly_credits: null,
    multiplier: 1,
    max_online: 1,
    highlights: ["按实际用量扣费，无月费", "余额不过期", "可随时升级到订阅套餐"],
  },
];

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[]>(FALLBACK_PLANS);
  const [checkoutPlan, setCheckoutPlan] = useState<Plan | null>(null);
  const [billing, setBilling] = useState<"month" | "year">("month");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/plans")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data?.plans?.length) setPlans(data.plans);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main id="top" className="page">
      <section className="hero hero--pricing">
        <div className="hero__tag reveal is-visible">定价</div>
        <h1 className="reveal is-visible">
          按你的办案强度
          <br />
          选一档
        </h1>
        <p className="hero__lead reveal is-visible" style={{ "--delay": "80ms" } as React.CSSProperties}>
          credits 是 Lawver 的用量单位：模型调用按 token、工具调用按次数扣费。
          订阅档位自带每月的 credits 额度，并按档位享受用量折扣。支付尚未开放，开通与充值请联系客服。
        </p>
      </section>

      <section className="section section--pricing">
        <div className="section__heading reveal is-visible">
          <span className="section__eyebrow">套餐</span>
          <h2>四档选择，随时可换</h2>
        </div>

        <div className="pricing-toggle reveal is-visible" role="group" aria-label="计费周期">
          <button
            type="button"
            className={billing === "month" ? "is-on" : ""}
            aria-pressed={billing === "month"}
            onClick={() => setBilling("month")}
          >
            按月
          </button>
          <button
            type="button"
            className={billing === "year" ? "is-on" : ""}
            aria-pressed={billing === "year"}
            onClick={() => setBilling("year")}
          >
            按年
            <small>省两个月</small>
          </button>
        </div>

        <div className="pricing-grid">
          {plans.map((plan, index) => (
            <article
              key={plan.id}
              className={"pricing-card reveal is-visible" + (plan.recommended ? " pricing-card--featured" : "")}
              style={{ "--delay": `${index * 60}ms` } as React.CSSProperties}
            >
              {plan.recommended && <span className="pricing-card__flag">最受欢迎</span>}
              <h3>{plan.name}</h3>
              <p className="pricing-card__tagline">{plan.tagline}</p>
              <div className="pricing-card__price">
                {plan.price_month === null ? (
                  <span className="pricing-card__consult">咨询客服</span>
                ) : plan.price_month === 0 ? (
                  <>
                    <strong>按量计费</strong>
                    <small>无月费</small>
                  </>
                ) : (
                  <>
                    <strong>¥{billing === "month" ? plan.price_month : plan.price_year}</strong>
                    <small>/ {billing === "month" ? "月" : "年"}</small>
                  </>
                )}
              </div>
              <ul className="pricing-card__features">
                {plan.highlights.map((item) => (
                  <li key={item}>
                    <Check size={15} strokeWidth={2.4} aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className="pricing-card__cta"
                onClick={() => setCheckoutPlan(plan)}
              >
                <MessageCircle size={16} strokeWidth={2} aria-hidden="true" />
                订阅
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="final">
        <div className="final__inner reveal is-visible">
          <h2>不确定选哪一档？</h2>
          <p>先按量充值试用，用量到一定规模再换订阅更划算。客服可以按你的实际用量给出建议。</p>
          <div className="final__actions">
            <Link className="primary-cta" to="/download">
              下载客户端
            </Link>
            <Link className="secondary-cta" to="/">
              回到首页
            </Link>
          </div>
        </div>
      </section>

      {checkoutPlan && (
        <CheckoutDialog plan={checkoutPlan} onClose={() => setCheckoutPlan(null)} />
      )}
    </main>
  );
}

/**
 * 开通弹窗：二维码是占位图，真实群码换上后把 KEFU_QR_IMAGE 指过去即可。
 * 每张卡的「订阅」都走这里——支付回调尚未接入，销售由客服一对一完成。
 */
function CheckoutDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="pricing-checkout"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pricing-checkout-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="pricing-checkout__panel">
        <button
          type="button"
          className="pricing-checkout__close"
          aria-label="关闭"
          ref={closeRef}
          onClick={onClose}
        >
          <X size={18} strokeWidth={2} />
        </button>
        <span className="pricing-checkout__plan">{plan.name}</span>
        <h2 id="pricing-checkout-title">扫码联系客服开通</h2>
        <p className="pricing-checkout__lead">
          支付通道尚未开放。添加客服后说明需要的档位，由我们为你开通并充值。
        </p>
        <div className="pricing-checkout__qr">
          {KEFU_QR_IMAGE ? (
            <img src={KEFU_QR_IMAGE} alt="客服群二维码" />
          ) : (
            <div className="pricing-checkout__qr-placeholder" role="img" aria-label="客服群二维码尚未发布">
              <span>暂未发售</span>
              <small>客服群二维码<br />上线后在此展示</small>
            </div>
          )}
        </div>
        <p className="pricing-checkout__note">
          开通后 credits 与账号绑定，可在「设置 → 用量」随时查看余额与流水。
        </p>
      </div>
    </div>
  );
}
