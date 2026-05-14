/*
 * 模块描述：登录表单组件，负责账号密码提交、错误展示和登录成功回调。
 */

import React, { useState } from 'react';
import { login } from '../services/api';
import { BrandMark } from './Brand';

interface LoginProps {
  onLoginSuccess: (username: string) => void;
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('请输入账号和密码');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      await login(username, password);
      onLoginSuccess(username);
    } catch (err: any) {
      setError(err.message || '登录失败，请检查账号密码');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(120%_80%_at_50%_0%,rgba(59,98,184,0.08)_0%,transparent_50%),var(--bg-app)] px-4 py-12 transition-colors duration-300 sm:px-6 lg:px-8">
      <div className="lawver-fade-up flex w-full max-w-md flex-col gap-7 rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-3)] sm:p-10">
        <div className="text-center">
          <BrandMark className="mx-auto h-14 w-14 text-[var(--accent)]" />
          <h2 className="t-headline-m mt-4">
            登录 Lawver
          </h2>
          <p className="t-body-s t-muted mt-2">
            仅限内部人员使用
          </p>
        </div>
        <form className="space-y-5" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] px-4 py-3 text-center text-sm text-[var(--color-danger-500)]">
              {error}
            </div>
          )}
          <div className="space-y-4">
            <div>
              <label className="sr-only" htmlFor="username">
                账号
              </label>
              <input
                id="username"
                type="text"
                required
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
                type="password"
                required
                className="md3-input"
                placeholder="密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={isLoading}
              className="md3-btn-filled lawver-pressable w-full rounded-[var(--radius-md)] py-3"
            >
              {isLoading ? '登录中…' : '登录'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
