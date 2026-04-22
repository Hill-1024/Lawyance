import { useState, useEffect, useCallback } from 'react';
import { fileDB } from '../lib/db';

export function useStorage() {
  const [usage, setUsage] = useState<number>(0);
  const [quota, setQuota] = useState<number>(0);
  const [isPersistent, setIsPersistent] = useState<boolean>(false);
  const [usageRatio, setUsageRatio] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  const updateEstimate = useCallback(async () => {
    if (!navigator.storage) {
      setError('当前浏览器环境不支持存储监控（可能是因为非 HTTPS 安全环境）。');
      return;
    }
    
    try {
      const estimate = await fileDB.getEstimate();
      setUsage(estimate.usage || 0);
      setQuota(estimate.quota || 0);
      if (estimate.quota) {
        setUsageRatio((estimate.usage || 0) / estimate.quota);
      }
      
      if (navigator.storage.persisted) {
        const persisted = await navigator.storage.persisted();
        setIsPersistent(persisted);
      }
    } catch (e) {
      console.error('Failed to get storage estimate:', e);
      setError('获取存储信息失败。');
    }
  }, []);

  const requestPersistence = async () => {
    if (!window.isSecureContext) {
      alert('持久化存储申请失败：必须在 HTTPS 安全环境（或 localhost）下才能申请此权限。');
      return false;
    }

    if (navigator.storage && navigator.storage.persist) {
      try {
        const granted = await navigator.storage.persist();
        setIsPersistent(granted);
        if (!granted) {
          console.warn('Storage persistence was denied by the browser.');
        }
        return granted;
      } catch (e) {
        console.error('Error requesting persistence:', e);
        return false;
      }
    }
    return false;
  };

  useEffect(() => {
    updateEstimate();
    // Check every minute
    const interval = setInterval(updateEstimate, 60000);
    return () => clearInterval(interval);
  }, [updateEstimate]);

  return {
    usage,
    quota,
    usageRatio,
    isPersistent,
    isLowStorage: usageRatio > 0.8 || (quota > 0 && quota - usage < 100 * 1024 * 1024), // > 80% or < 100MB
    updateEstimate,
    requestPersistence,
    error
  };
}
