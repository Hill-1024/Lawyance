/*
 * 模块描述：登录表单组件，负责账号密码提交、错误展示和登录成功回调。
 * 视觉沿用工作台 island 语言（暖画布 + 一张白卡 + 品牌组合字标），样式见同目录 login.css。
 */

import React, { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowLeft, ShieldAlert } from 'lucide-react';
import { login, type LoginResult } from '../services/api';
import { BrandLockup } from './Brand';
import { useT } from '../i18n';
import './login.css';

interface LoginProps {
  onLoginSuccess: (result: LoginResult) => void;
  /** 通过 IP 直连时的安全提示等页级通知，与卡片同列居中。 */
  notice?: React.ReactNode;
}

const ENTER_EASE = [0.16, 1, 0.3, 1] as const;

export const Login: React.FC<LoginProps> = ({ onLoginSuccess, notice }) => {
  const { t } = useT();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const reduceMotion = Boolean(useReducedMotion());
  const passwordRef = useRef<HTMLInputElement>(null);
  // 失败后要把焦点放回密码框：必须等提交后的这一帧落地（输入框还是 disabled 时 focus/select 都无效）。
  const refocusPassword = useRef(false);
  useEffect(() => {
    if (isLoading || !refocusPassword.current) return;
    refocusPassword.current = false;
    passwordRef.current?.focus();
    passwordRef.current?.select();
  }, [isLoading]);

  const submit = async () => {
    if (!username.trim() || !password.trim()) {
      setError(t('login.missingCredentials'));
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const result = await login(username, password);
      onLoginSuccess(result);
    } catch (err: any) {
      setError(err.message || t('login.failed'));
      // 重新输入比重新点一遍表单快：标记回焦，交给上面的 effect 在提交后执行。
      refocusPassword.current = true;
    } finally {
      setIsLoading(false);
    }
  };

  // 密码框里按 Enter 也要能登录：不依赖浏览器的隐式提交（实测在部分内嵌环境不触发）。
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    void submit();
  };

  return (
    <div className="lg-page">
      {notice}
      <motion.section
        className="lg-sheet"
        aria-labelledby="login-title"
        initial={reduceMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.42, ease: ENTER_EASE }}
      >
        <header className="lg-head">
          <BrandLockup />
          <h1 className="lg-title" id="login-title">
            {t("login.title")}
          </h1>
        </header>

        <form
          className="lg-form"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {/* role=alert + aria-live：读屏也能听到失败原因，而不仅是视觉上出现。 */}
          <div aria-live="assertive" aria-atomic="true">
            {error && (
              <p className="lg-alert" role="alert">
                <ShieldAlert size={15} strokeWidth={2} aria-hidden="true" />
                <span>{error}</span>
              </p>
            )}
          </div>

          <div className="lg-field">
            <label className="lg-label" htmlFor="username">
              {t("login.username")}
            </label>
            <input
              id="username"
              name="username"
              type="text"
              required
              autoFocus
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="next"
              className="lg-input"
              placeholder={t("login.usernamePlaceholder")}
              value={username}
              disabled={isLoading}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  passwordRef.current?.focus();
                }
              }}
            />
          </div>

          <div className="lg-field">
            <label className="lg-label" htmlFor="password">
              {t("login.password")}
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              ref={passwordRef}
              autoComplete="current-password"
              enterKeyHint="go"
              className="lg-input"
              placeholder={t("login.passwordPlaceholder")}
              value={password}
              disabled={isLoading}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
            />
          </div>

          <button type="submit" className="lg-submit" disabled={isLoading} aria-busy={isLoading}>
            {isLoading ? (
              <>
                <span className="lg-spin" aria-hidden="true" />
                {t("login.loggingIn")}
              </>
            ) : (
              t('login.submit')
            )}
          </button>
        </form>

        <footer className="lg-foot">
          <RouterLink to="/" className="lg-link">
            <ArrowLeft size={14} strokeWidth={2} aria-hidden="true" />
            {t("login.backHome")}
          </RouterLink>
        </footer>
      </motion.section>
    </div>
  );
};
