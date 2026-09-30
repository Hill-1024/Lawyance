/*
 * 模块描述：前端启动入口，将 React 应用挂载到 DOM 并接入浏览器路由。
 */

import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MotionConfig } from 'motion/react';
import App from './App';
import { I18nProvider } from './i18n';
import { DialogProvider } from './contexts/DialogContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { setupNativeChrome } from './lib/native-bootstrap';
import { registerPwa } from './lib/pwa';
import { BASE_PATH } from './lib/app-config';
import './index.css';

setupNativeChrome().catch(console.error);
registerPwa();

/*
 * reducedMotion="user" 是全局兜底：motion/react 走 WAAPI，index.css 里针对
 * animation-duration / transition-duration 的 prefers-reduced-motion 覆盖管不到它。
 * 放在这里，任何新写的 motion 组件默认就尊重系统设置，不必逐个记得判断。
 * 需要更细的降级（例如把位移换成纯淡入）时，组件内仍可用 useReducedMotion 覆盖。
 */
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <BrowserRouter basename={BASE_PATH || undefined}>
        <I18nProvider>
          <ThemeProvider>
            <DialogProvider>
              <App />
            </DialogProvider>
          </ThemeProvider>
        </I18nProvider>
      </BrowserRouter>
    </MotionConfig>
  </StrictMode>,
);
