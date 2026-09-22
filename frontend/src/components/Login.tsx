/*
 * 模块描述：登录表单组件，负责账号密码提交、错误展示和登录成功回调。
 */

import React, { useState } from 'react';
import { login, type LoginResult } from '../services/api';
import { useTranslation } from '../contexts/LocaleContext';
import { BrandMark } from './Brand';

interface LoginProps {
  onLoginSuccess: (result: LoginResult) => void;
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const t = useTranslation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError(t('login.error.empty'));
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const result = await login(username, password);
      onLoginSuccess(result);
    } catch (err: any) {
      setError(err.message || t('login.error.failed'));
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
            {t('login.title')}
          </h2>
          <p className="t-body-s t-muted mt-2">
            {t('login.subtitle')}
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
                {t('login.username')}
              </label>
              <input
                id="username"
                type="text"
                required
                className="md3-input"
                placeholder={t('login.username')}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div>
              <label className="sr-only" htmlFor="password">
                {t('login.password')}
              </label>
              <input
                id="password"
                type="password"
                required
                className="md3-input"
                placeholder={t('login.password')}
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
              {isLoading ? t('login.submitting') : t('login.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
