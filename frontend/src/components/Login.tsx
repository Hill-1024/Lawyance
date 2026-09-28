/*
 * 模块描述：登录表单组件，负责账号密码提交、错误展示和登录成功回调。
 */

import React, { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowLeft, ShieldAlert } from 'lucide-react';
import { login, type LoginResult } from '../services/api';
import { BrandMark } from './Brand';

interface LoginProps {
  onLoginSuccess: (result: LoginResult) => void;
}

const ENTER_EASE = [0.16, 1, 0.3, 1] as const;

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const reduceMotion = Boolean(useReducedMotion());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('请输入账号和密码');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const result = await login(username, password);
      onLoginSuccess(result);
    } catch (err: any) {
      setError(err.message || '登录失败，请检查账号密码');
    } finally {
      setIsLoading(false);
    }
  };

  /*
   * 入场用一次分层的淡入（品牌 → 表单 → 底部返回），而不是逐个元素各动一遍：
   * 登录页每次都是冷启动第一屏，需要交代“先看标题、再填表”的次序。
   * 关闭动效时直接落到终态，不做位移。
   */
  const enter = (delay: number) => (reduceMotion
    ? { initial: false as const, animate: { opacity: 1 } }
    : {
      initial: { opacity: 0, y: 14 },
      animate: { opacity: 1, y: 0 },
      transition: { duration: 0.5, delay, ease: ENTER_EASE },
    });

  return (
    <div className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden bg-[var(--bg-app)] px-4 py-12 transition-colors duration-300 sm:px-6 lg:px-8">
      {/* 与空会话首屏同一套语言：一层极淡的强调色光晕，让登录页不像一个孤立的表单。 */}
      <div
        className="pointer-events-none absolute inset-x-0 top-[12%] mx-auto h-72 max-w-xl rounded-full bg-[var(--accent)] opacity-[0.06] blur-3xl"
        aria-hidden="true"
      />

      <div className="relative w-full max-w-md">
        <motion.div
          {...enter(0)}
          className="flex flex-col gap-7 rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-3)] sm:p-10"
        >
          <div className="text-center">
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={reduceMotion ? { duration: 0.01 } : { type: 'spring', damping: 22, stiffness: 260 }}
              className="mx-auto flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--accent-quiet)]"
            >
              <BrandMark className="h-9 w-9 text-[var(--accent)]" />
            </motion.div>
            <h1 className="t-headline-m mt-4">
              登录 Lawver
            </h1>
            <p className="t-body-s t-muted mt-2">
              仅限内部人员使用
            </p>
          </div>

          <form className="space-y-5" onSubmit={handleSubmit} noValidate>
            {/* role=alert 让读屏软件念出失败原因：原来错误只在视觉上出现，辅助技术完全收不到。 */}
            <div aria-live="assertive" aria-atomic="true">
              {error && (
                <div
                  role="alert"
                  className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] px-4 py-3 text-sm text-[var(--color-danger-500)]"
                >
                  <ShieldAlert size={16} strokeWidth={2} className="mt-0.5 shrink-0" />
                  <span className="min-w-0 flex-1">{error}</span>
                </div>
              )}
            </div>

            <motion.div {...enter(0.06)} className="space-y-4">
              <div>
                <label className="sr-only" htmlFor="username">
                  账号
                </label>
                <input
                  id="username"
                  name="username"
                  type="text"
                  required
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  className="md3-input"
                  placeholder="账号"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div>
                <label className="sr-only" htmlFor="password">
                  密码
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  autoComplete="current-password"
                  className="md3-input"
                  placeholder="密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </motion.div>

            <motion.div {...enter(0.12)}>
              <button
                type="submit"
                disabled={isLoading}
                aria-busy={isLoading}
                className="md3-btn-filled lawver-pressable w-full py-3"
              >
                {isLoading ? '登录中…' : '登录'}
              </button>
            </motion.div>
          </form>
        </motion.div>

        {/* 登录页是受守卫路由的入口，此前没有任何回到公开页面的出口。 */}
        <motion.div {...enter(0.18)} className="mt-5 text-center">
          <RouterLink
            to="/"
            className="lawver-pressable inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 text-[13px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg-1)]"
          >
            <ArrowLeft size={15} strokeWidth={2} />
            返回首页
          </RouterLink>
        </motion.div>
      </div>
    </div>
  );
};
