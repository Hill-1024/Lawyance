/*
 * 模块描述：自助用量控制台（/usage）——所有登录用户可见，Business 子账号看到的
 * 是自己的用量。数字卡 + 每日 credits 折线图 + token 构成环图，观察跨度可选
 * 7/14/30/90 天（后端夹取上限）。视觉复用 Business 控制台的岛式壳（wb-business-*
 * 类），图表为手写 SVG：只动 path/circle，不引图表库。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react';
import { BrandMark } from '../components/Brand';
import { HoverInfo } from '../components/HoverInfo';
import { Banner } from '../components/settings/SettingsUI';
import { useAppBack } from '../hooks/useAppBack';
import { useT, type MessageKey } from '../i18n';
import {
  cancelScheduledPlanChange,
  fetchUsageSummary,
  schedulePlanChange,
  type UsageSummary,
} from '../services/api';
import '../workbench/workbench.css';
import './usage.css';

const RANGES = [7, 14, 30, 90] as const;

const formatCredits = (value: number) =>
  value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const formatTokens = (value: number) =>
  value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN', { maximumFractionDigits: 0 });

/** 每日 credits 折线 + 渐变面积。series 升序、已补零。 */
const CreditsLineChart: React.FC<{ series: UsageSummary['series'] }> = ({ series }) => {
  const width = 640;
  const height = 190;
  const padX = 8;
  const padTop = 12;
  const padBottom = 22;
  const max = Math.max(1, ...series.map((d) => d.credits));
  const stepX = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
  const points = series.map((d, i) => ({
    x: padX + i * stepX,
    y: padTop + (1 - d.credits / max) * (height - padTop - padBottom),
    d,
  }));
  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const area = `${line} L${points[points.length - 1]?.x.toFixed(1) ?? padX},${height - padBottom} L${padX},${height - padBottom} Z`;
  const last = series[series.length - 1];
  const lastPoint = points[points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="wb-usage-line"
      role="img"
      aria-label="每日 credits 消耗折线图"
    >
      <defs>
        <linearGradient id="wb-usage-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((ratio) => (
        <line
          key={ratio}
          x1={padX}
          x2={width - padX}
          y1={padTop + ratio * (height - padTop - padBottom)}
          y2={padTop + ratio * (height - padTop - padBottom)}
          stroke="var(--border-subtle)"
          strokeDasharray="3 5"
        />
      ))}
      <path d={area} fill="url(#wb-usage-area)" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {lastPoint && (
        <circle cx={lastPoint.x} cy={lastPoint.y} r="3.5" fill="var(--accent)" />
      )}
      <text x={padX} y={height - 6} className="wb-usage-axis">
        {series[0]?.day.slice(5)}
      </text>
      <text x={width - padX} y={height - 6} textAnchor="end" className="wb-usage-axis">
        {last?.day.slice(5)}
      </text>
      <text x={padX} y={padTop + 8} className="wb-usage-axis">
        峰值 {formatCredits(max)}
      </text>
    </svg>
  );
};

/** Token 构成环图：输入 vs 输出（同单位，占比才有意义）。 */
const TokenDonut: React.FC<{ prompt: number; completion: number }> = ({ prompt, completion }) => {
  const total = Math.max(1, prompt + completion);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const promptShare = prompt / total;
  return (
    <div className="wb-usage-donut-wrap">
      <svg viewBox="0 0 140 140" className="wb-usage-donut" role="img" aria-label="Token 输入输出构成环图">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="var(--brand-primary-100)" strokeWidth="16" />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="16"
          strokeDasharray={`${(promptShare * circumference).toFixed(1)} ${circumference.toFixed(1)}`}
          strokeLinecap="butt"
          transform="rotate(-90 70 70)"
        />
        <text x="70" y="66" textAnchor="middle" className="wb-usage-donut-number">
          {Math.round(promptShare * 100)}%
        </text>
        <text x="70" y="84" textAnchor="middle" className="wb-usage-donut-label">
          输入占比
        </text>
      </svg>
      <dl className="wb-usage-legend">
        <div>
          <dt>
            <span className="wb-usage-dot" style={{ background: 'var(--accent)' }} /> 输入 tokens
          </dt>
          <dd>{formatTokens(prompt)}</dd>
        </div>
        <div>
          <dt>
            <span className="wb-usage-dot" style={{ background: 'var(--brand-primary-100)' }} /> 输出 tokens
          </dt>
          <dd>{formatTokens(completion)}</dd>
        </div>
      </dl>
    </div>
  );
};

export default function UsageConsole() {
  const { t } = useT();
  const goBack = useAppBack();
  const [days, setDays] = useState<number>(30);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [subBusy, setSubBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogError, setDialogError] = useState('');

  const load = useCallback(
    async (windowDays: number) => {
      setLoading(true);
      setError('');
      try {
        setSummary(await fetchUsageSummary(windowDays));
      } catch (e) {
        setError((e as Error).message || t('usage.loadFailed'));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const totals = summary?.totals;
  const tokens = useMemo(() => totals?.tokens ?? 0, [totals]);

  const shell = (children: React.ReactNode) => (
    <div className="wb-app wb-business">
      <div className="wb-business-shell">
        <header className="wb-business-head">
          <div className="wb-business-identity">
            <HoverInfo label={t('usage.back')} placement="bottom">
              <button aria-label={t('usage.back')} onClick={() => goBack('/')}>
                <ArrowLeft size={18} />
              </button>
            </HoverInfo>
            <span className="wb-business-mark">
              <BrandMark className="h-5 w-5" />
            </span>
            <div className="wb-business-title">
              <h1>{t('usage.title')}</h1>
              <p>{t('usage.subtitle')}</p>
            </div>
          </div>
          <div className="wb-business-head-actions">
            <button className="wb-quiet" onClick={() => void load(days)} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'wb-spin' : undefined} />
              {t('usage.refresh')}
            </button>
          </div>
        </header>
        <main className="wb-business-main">{children}</main>
      </div>
    </div>
  );

  if (loading && !summary) {
    return shell(
      <p className="wb-business-loading">
        <Loader2 size={18} className="wb-spin" /> {t('usage.loading')}
      </p>,
    );
  }

  const applySummary = (next: UsageSummary) => setSummary(next);

  const cancelChange = async () => {
    setSubBusy(true);
    try {
      await cancelScheduledPlanChange();
      applySummary(await fetchUsageSummary(days));
    } catch (e) {
      setError((e as Error).message || t('usage.loadFailed'));
    } finally {
      setSubBusy(false);
    }
  };

  const scheduleMetered = async () => {
    setSubBusy(true);
    try {
      await schedulePlanChange('metered');
      setDialogOpen(false);
      applySummary(await fetchUsageSummary(days)); // 预约状态回填到当前订阅卡
    } catch (e) {
      setDialogError((e as Error).message || t('usage.loadFailed'));
    } finally {
      setSubBusy(false);
    }
  };

  const planName = (plan: string) => {
    const keys: Record<string, MessageKey> = {
      metered: 'usage.planMetered',
      go: 'usage.planGo',
      pro: 'usage.planPro',
      max: 'usage.planMax',
      business: 'usage.planBusiness',
    };
    return t(keys[plan] ?? 'usage.planMetered');
  };

  return shell(
    <>
      {error && <Banner tone="danger">{error}</Banner>}

      {/* 当前订阅：档位、预约中的变更与取消入口 */}
      <section className="wb-usage-sub" aria-label={t('usage.subLabel')}>
        <div className="wb-usage-sub-main">
          <span className="wb-usage-sub-label">{t('usage.subLabel')}</span>
          <span className="wb-usage-sub-plan">
            {summary ? planName(summary.plan) : '…'}
            {summary?.pending_plan && (
              <span className="wb-usage-sub-pending" role="status">
                {t('usage.pendingTo', {
                  plan: planName(summary.pending_plan),
                  date: (summary.pending_effective_at || '').slice(0, 10),
                })}
              </span>
            )}
          </span>
        </div>
        <div className="wb-usage-sub-actions">
          {summary?.pending_plan ? (
            <button type="button" className="wb-quiet" disabled={subBusy} onClick={() => void cancelChange()}>
              {t('usage.cancelChange')}
            </button>
          ) : summary && summary.plan !== 'metered' && summary.plan !== 'business' ? (
            <button type="button" className="wb-quiet" disabled={subBusy} onClick={() => { setDialogOpen(true); setDialogError(''); }}>
              {t('usage.cancelSub')}
            </button>
          ) : null}
        </div>
      </section>

      {/* 取消订阅确认弹窗（= 预约切回按量，权益保留到本周期结束） */}
      {dialogOpen && (
        <div
          className="wb-modal-backdrop"
          onMouseDown={(e) => { if (e.target === e.currentTarget) setDialogOpen(false); }}
        >
          <section className="wb-nudge" role="dialog" aria-modal="true" aria-labelledby="wb-cancel-title">
            <h2 id="wb-cancel-title">{t('usage.cancelDialogTitle')}</h2>
            <p className="wb-nudge__body">
              {t('usage.cancelDialogBody', {
                date: (summary?.pending_effective_at || summary && '').slice(0, 10) || t('usage.pendingSoon'),
              })}
            </p>
            {dialogError && <p className="wb-usage-dialog-error" role="alert">{dialogError}</p>}
            <div className="wb-nudge__actions">
              <button type="button" className="wb-nudge__quiet" onClick={() => setDialogOpen(false)}>
                {t('usage.cancelDialogCancel')}
              </button>
              <button type="button" className="wb-nudge__upgrade" disabled={subBusy} onClick={() => void scheduleMetered()}>
                {t('usage.cancelDialogConfirm')}
              </button>
            </div>
          </section>
        </div>
      )}

      {/* 跨度选择：7 / 14 / 30 / 90 天 */}
      <div className="wb-usage-ranges" role="group" aria-label={t('usage.rangeLabel')}>
        {RANGES.map((value) => (
          <button
            key={value}
            type="button"
            className={'wb-usage-range' + (days === value ? ' is-active' : '')}
            aria-pressed={days === value}
            onClick={() => setDays(value)}
          >
            {t('usage.rangeDays', { days: value })}
          </button>
        ))}
      </div>

      <section className="wb-business-stats" aria-label={t('usage.statsLabel')}>
        <div className="wb-business-stat">
          <span>{t('usage.balanceLabel')}</span>
          <strong>{summary ? formatCredits(summary.balance) : '…'}</strong>
          <small>credits</small>
        </div>
        <div className="wb-business-stat">
          <span>{t('usage.spentLabel', { days })}</span>
          <strong>{totals ? formatCredits(totals.credits) : '…'}</strong>
          <small>credits</small>
        </div>
        <div className="wb-business-stat">
          <span>{t('usage.tokensLabel')}</span>
          <strong>{formatTokens(tokens)}</strong>
          <small>tokens</small>
        </div>
        <div className="wb-business-stat">
          <span>{t('usage.toolsLabel')}</span>
          <strong>{(totals?.tool_calls ?? 0).toLocaleString('zh-CN')}</strong>
          <small>{t('usage.callsUnit')}</small>
        </div>
      </section>

      <div className="wb-usage-charts">
        <section className="wb-usage-card" aria-label={t('usage.lineTitle')}>
          <h2>{t('usage.lineTitle')}</h2>
          <CreditsLineChart series={summary?.series ?? []} />
        </section>
        <section className="wb-usage-card" aria-label={t('usage.donutTitle')}>
          <h2>{t('usage.donutTitle')}</h2>
          <TokenDonut
            prompt={totals?.prompt_tokens ?? 0}
            completion={totals?.completion_tokens ?? 0}
          />
        </section>
      </div>
    </>,
  );
}
