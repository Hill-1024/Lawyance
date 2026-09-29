/*
 * 模块描述：Business 控制台——母账号查看子账号、分配 credits，并在有权限时停用/启用。
 *
 * /api/business/* 只对 business 套餐开放；非 business 账号拿 403，这里渲染
 * 「仅 Business 账号可用」的说明页，不当作异常处理。停用/启用走的是 staff 接口
 * /api/admin/accounts/{username}/status：探到无权限就整列隐藏并说明，不做假成功。
 * 视觉沿用工作台岛式语言（.wb-app 令牌、--wb-control-size 控件网格），
 * 样式在 workbench.business.css。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Loader2,
  Power,
  RefreshCw,
  ShieldAlert,
  Users,
  Wallet,
} from 'lucide-react';
import { BrandMark } from '../components/Brand';
import { HoverInfo } from '../components/HoverInfo';
import { Banner, EmptyState, StatusChip } from '../components/settings/SettingsUI';
import { useAppDialog } from '../contexts/DialogContext';
import { useAppBack } from '../hooks/useAppBack';
import {
  allocateSubaccountCredits,
  apiFetch,
  createSubaccount,
  fetchBusinessOverview,
  PlanForbiddenError,
  setSubaccountStatus,
  type BusinessOverview,
  type BusinessSubAccount,
  type UsageRow,
} from '../services/api';
import '../workbench/workbench.css';

/* ── 格式化与统计 ─────────────────────────────────────────────────────── */

const formatCredits = (value: number | null | undefined) =>
  Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const formatCount = (value: number | null | undefined) =>
  Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 });

/** tokens 动辄百万级，用「万」压缩；不足一万保留精确值。 */
const formatTokens = (value: number) =>
  value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : formatCount(value);

/** 用量行按天倒序返回，只取最近 30 天；上限之外的老数据不参与统计。 */
const recentUsage = (rows: UsageRow[]) => rows.slice(0, 30);

const sumUsage = (rows: UsageRow[]) =>
  rows.reduce(
    (total, row) => ({
      tokens: total.tokens + (row.prompt_tokens || 0) + (row.completion_tokens || 0),
      tools: total.tools + (row.tool_calls || 0),
      credits: total.credits + (row.credits || 0),
    }),
    { tokens: 0, tools: 0, credits: 0 },
  );

const isForbidden = (message: string) => /admin access required|权限|forbidden/i.test(message);

/* ── 子账号卡片 ───────────────────────────────────────────────────────── */

const SubAccountCard: React.FC<{
  item: BusinessSubAccount;
  canManageStatus: boolean;
  onAllocated: (username: string, parentCredits: number, childCredits: number) => void;
  onStatusChanged: (username: string, status: string) => void;
  onStatusForbidden: () => void;
}> = ({ item, canManageStatus, onAllocated, onStatusChanged, onStatusForbidden }) => {
  const { showConfirm } = useAppDialog();
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [failure, setFailure] = useState('');
  const suspended = item.status === 'suspended';
  const recent = useMemo(() => recentUsage(item.usage), [item.usage]);
  const totals = useMemo(() => sumUsage(recent), [recent]);
  const peak = useMemo(() => Math.max(1, ...recent.map(row => row.credits || 0)), [recent]);
  // 行按天倒序，柱子按时间正序从左到右。
  const bars = useMemo(() => [...recent].reverse(), [recent]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setNotice('');
      setFailure('请输入大于 0 的 credits 数量。');
      return;
    }
    setBusy('allocate');
    setFailure('');
    setNotice('');
    try {
      const result = await allocateSubaccountCredits(item.username, value);
      setAmount('');
      onAllocated(item.username, result.parent_credits, result.child_credits);
      setNotice(
        `已分配 ${formatCredits(value)} credits：母账号 ${formatCredits(result.parent_credits)} · ${item.username} ${formatCredits(result.child_credits)}`,
      );
    } catch (e) {
      setFailure((e as Error).message || '分配 credits 失败。');
    } finally {
      setBusy('');
    }
  };

  const toggleStatus = async () => {
    const nextStatus = suspended ? 'active' : 'suspended';
    const confirmed = await showConfirm({
      title: suspended ? '启用子账号？' : '停用子账号？',
      message: suspended
        ? `启用后「${item.username}」可以重新登录并使用。`
        : `停用后「${item.username}」将无法登录，在线设备立即下线。`,
      tone: suspended ? 'info' : 'danger',
      confirmLabel: suspended ? '启用' : '停用',
    });
    if (!confirmed) return;
    setBusy('status');
    setFailure('');
    setNotice('');
    try {
      await setSubaccountStatus(item.username, nextStatus);
      onStatusChanged(item.username, nextStatus);
      setNotice(`「${item.username}」已${suspended ? '启用' : '停用'}。`);
    } catch (e) {
      const message = (e as Error).message || '更新账号状态失败。';
      // 权限在会话中途变化时同样收手：隐藏按钮并说明，不留下假成功的假象。
      if (isForbidden(message)) {
        onStatusForbidden();
        setFailure('停用/启用需要管理员权限，当前账号不可用。');
      } else {
        setFailure(message);
      }
    } finally {
      setBusy('');
    }
  };

  return (
    <article className="wb-business-card">
      <header className="wb-business-card-head">
        <div className="wb-business-card-user">
          <span className="wb-business-avatar" aria-hidden="true">
            <Users size={15} />
          </span>
          <strong>{item.username}</strong>
          <StatusChip tone={suspended ? 'danger' : 'ok'}>{suspended ? '已停用' : '正常'}</StatusChip>
        </div>
        {canManageStatus && (
          <button
            type="button"
            className={`wb-quiet${suspended ? '' : ' wb-danger'}`}
            disabled={busy === 'status'}
            onClick={() => void toggleStatus()}
          >
            {busy === 'status' ? (
              <Loader2 size={15} className="wb-spin" />
            ) : (
              <Power size={15} />
            )}
            {suspended ? '启用' : '停用'}
          </button>
        )}
      </header>

      <div className="wb-business-metrics">
        <div className="wb-business-metric">
          <span>余额</span>
          <strong>{formatCredits(item.credits)}</strong>
        </div>
        <div className="wb-business-metric">
          <span>预算上限</span>
          <strong>{item.quota == null ? '不限' : formatCredits(item.quota)}</strong>
        </div>
        <div className="wb-business-metric">
          <span>近 30 天 tokens</span>
          <strong>{formatTokens(totals.tokens)}</strong>
        </div>
        <div className="wb-business-metric">
          <span>工具调用</span>
          <strong>{formatCount(totals.tools)}</strong>
        </div>
        <div className="wb-business-metric">
          <span>近 30 天 credits</span>
          <strong>{formatCredits(totals.credits)}</strong>
        </div>
      </div>

      <div
        className="wb-business-spark"
        role="img"
        aria-label={`近 30 天每日 credits，单日最高 ${formatCredits(peak)}`}
      >
        {bars.map(row => (
          <span
            key={row.day}
            style={{ height: `${row.credits > 0 ? Math.max(8, (row.credits / peak) * 100) : 3}%` }}
            title={`${row.day} · ${formatCredits(row.credits)} credits · ${formatTokens((row.prompt_tokens || 0) + (row.completion_tokens || 0))} tokens`}
          />
        ))}
        {!bars.length && <span className="wb-business-spark-empty">近 30 天没有用量</span>}
      </div>

      <form className="wb-business-allocate" onSubmit={submit}>
        <label>
          <span>分配 credits</span>
          <input
            className="wb-business-input"
            type="number"
            inputMode="decimal"
            min="0.01"
            step="any"
            value={amount}
            placeholder="0.00"
            onChange={e => setAmount(e.target.value)}
            aria-label={`给 ${item.username} 分配 credits`}
          />
        </label>
        <button type="submit" className="wb-primary" disabled={busy === 'allocate' || !amount.trim()}>
          {busy === 'allocate' ? <Loader2 size={15} className="wb-spin" /> : <Wallet size={15} />}
          分配
        </button>
      </form>

      {notice && (
        <p className="wb-business-ok" role="status">
          {notice}
        </p>
      )}
      {failure && (
        <p className="wb-business-error" role="alert">
          {failure}
        </p>
      )}
    </article>
  );
};

/* ── 页面 ─────────────────────────────────────────────────────────────── */

export const BusinessConsole: React.FC = () => {
  const goBack = useAppBack();
  const [overview, setOverview] = useState<BusinessOverview>();
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  // 停用/启用是 staff 接口：进来先探一次权限，没有就整列隐藏。
  const [canManageStatus, setCanManageStatus] = useState(false);
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const alive = useRef(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const next = await fetchBusinessOverview();
      if (!alive.current) return;
      setOverview(next);
      // 停用/启用走 Business 自己的端点（PATCH /api/business/subaccounts/:u/status），
      // 不再依赖管理员权限探测。
      setCanManageStatus(true);
      setForbidden(false);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof PlanForbiddenError) {
        setForbidden(true);
        setOverview(undefined);
      } else {
        setError((e as Error).message || '读取子账号失败。');
      }
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  const createSub = async () => {
    setCreateBusy(true);
    try {
      await createSubaccount(newName.trim(), newPassword);
      setNewName('');
      setNewPassword('');
      await load();
    } catch (e: any) {
      setError((e as Error).message || '创建子账号失败。');
    } finally {
      setCreateBusy(false);
    }
  };

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const subaccounts = useMemo(() => overview?.subaccounts || [], [overview]);
  const totals = useMemo(() => sumUsage(subaccounts.flatMap(item => recentUsage(item.usage))), [subaccounts]);

  const handleAllocated = useCallback(
    (username: string, parentCredits: number, childCredits: number) => {
      setOverview(prev =>
        prev
          ? {
              ...prev,
              parent_credits: parentCredits,
              subaccounts: prev.subaccounts.map(item =>
                item.username === username ? { ...item, credits: childCredits } : item,
              ),
            }
          : prev,
      );
    },
    [],
  );

  const handleStatusChanged = useCallback((username: string, status: string) => {
    setOverview(prev =>
      prev
        ? {
            ...prev,
            subaccounts: prev.subaccounts.map(item =>
              item.username === username ? { ...item, status } : item,
            ),
          }
        : prev,
    );
  }, []);

  const shell = (children: React.ReactNode) => (
    <div className="wb-app wb-business">
      <div className="wb-business-shell">
        <header className="wb-business-head">
          <div className="wb-business-identity">
            <HoverInfo label="返回工作台" placement="bottom">
              <button aria-label="返回工作台" onClick={() => goBack('/')}>
                <ArrowLeft size={18} />
              </button>
            </HoverInfo>
            <span className="wb-business-mark">
              <BrandMark className="h-5 w-5" />
            </span>
            <div className="wb-business-title">
              <h1>Business 控制台</h1>
              <p>子账号预算、状态与近期用量</p>
            </div>
          </div>
          <div className="wb-business-head-actions">
            <button className="wb-quiet" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'wb-spin' : undefined} />
              刷新
            </button>
          </div>
        </header>
        <main className="wb-business-main">{children}</main>
      </div>
    </div>
  );

  if (loading && !overview && !forbidden) {
    return shell(
      <p className="wb-business-loading">
        <Loader2 size={18} className="wb-spin" /> 正在读取子账号…
      </p>,
    );
  }

  if (forbidden) {
    return shell(
      <EmptyState
        className="wb-business-refusal"
        icon={<ShieldAlert size={22} strokeWidth={2} />}
        title="仅 Business 账号可用"
        description="当前账号不是 Business 套餐，无法管理子账号。如需为多名成员分配预算，请联系管理员开通 Business 套餐。"
        action={
          <button type="button" className="wb-primary" onClick={() => goBack('/')}>
            返回工作台
          </button>
        }
      />,
    );
  }

  if (!overview) {
    return shell(
      <>
        {error && <Banner tone="danger">{error}</Banner>}
        <div>
          <button type="button" className="wb-quiet" onClick={() => void load()}>
            <RefreshCw size={15} /> 重试
          </button>
        </div>
      </>,
    );
  }

  const used = subaccounts.length;
  return shell(
    <>
      {error && <Banner tone="danger">{error}</Banner>}

      <section className="wb-business-stats" aria-label="Business 概览">
        <div className="wb-business-stat">
          <span>母账号余额</span>
          <strong>{formatCredits(overview.parent_credits)}</strong>
          <small>credits</small>
        </div>
        <div className="wb-business-stat">
          <span>子账号</span>
          <strong>
            {used} / {overview.max_users == null ? '不限' : overview.max_users}
          </strong>
          <small>已用 / 上限</small>
        </div>
        <div className="wb-business-stat">
          <span>子账号近 30 天消耗</span>
          <strong>{formatCredits(totals.credits)}</strong>
          <small>credits</small>
        </div>
      </section>

      <div className="wb-business-list-head">
        <h2 className="wb-business-section-title">子账号</h2>
        <div className="wb-business-create">
          <input
            aria-label="子账号名"
            placeholder="子账号名"
            value={newName}
            maxLength={128}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            aria-label="子账号密码"
            placeholder="初始密码（至少 6 位）"
            type="password"
            value={newPassword}
            maxLength={1024}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <button
            type="button"
            className="md3-btn-tonal"
            disabled={createBusy || newName.trim().length < 1 || newPassword.length < 6}
            onClick={() => void createSub()}
          >
            {createBusy ? '创建中…' : '新建子账号'}
          </button>
        </div>
      </div>

      {used === 0 ? (
        <EmptyState
          className="wb-business-refusal"
          icon={<Users size={22} strokeWidth={2} />}
          title="还没有子账号"
          description="用上面的表单创建第一个子账号，然后在这里查看用量并分配预算。"
        />
      ) : (
        <div className="wb-business-cards">
          {subaccounts.map(item => (
            <SubAccountCard
              key={item.username}
              item={item}
              canManageStatus={canManageStatus}
              onAllocated={handleAllocated}
              onStatusChanged={handleStatusChanged}
              onStatusForbidden={() => setCanManageStatus(false)}
            />
          ))}
        </div>
      )}
    </>,
  );
};

export default BusinessConsole;
