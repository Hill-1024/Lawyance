/*
 * 模块描述：应用内返回导航 hook，把 app-history 的决策落到 react-router。
 */

import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { appHistoryIndex, planAppBack } from '../lib/app-history';

/**
 * 退栈优先的返回；父级路径在调用时给出，便于一个页面服务多个入口。
 *
 * 不要用 navigate(父级) 代替它：那是压栈，会让用户再按返回时回到刚离开的子页。
 */
export const useAppBack = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return useCallback((parentPath: string) => {
    const plan = planAppBack({
      pathname: location.pathname,
      historyIndex: appHistoryIndex(),
      parentPath,
    });
    if (plan.type === 'pop') {
      navigate(-1);
      return;
    }
    if (plan.type === 'replace') {
      navigate(plan.to, { replace: true });
    }
  }, [navigate, location.pathname]);
};

/** 父级由路径推导，返回 false 表示已到根路由，供 Android 物理返回键决定是否退出应用。 */
export const useAppBackUp = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return useCallback((): boolean => {
    const plan = planAppBack({
      pathname: location.pathname,
      historyIndex: appHistoryIndex(),
    });
    if (plan.type === 'exit') return false;
    if (plan.type === 'pop') {
      navigate(-1);
      return true;
    }
    navigate(plan.to, { replace: true });
    return true;
  }, [navigate, location.pathname]);
};
