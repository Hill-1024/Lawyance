/*
 * 模块描述：前端启动入口，将 React 应用挂载到 DOM 并接入浏览器路由。
 */

import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { DialogProvider } from './contexts/DialogContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { setupNativeChrome } from './lib/native-bootstrap';
import { registerPwa } from './lib/pwa';
import './index.css';

setupNativeChrome().catch(console.error);
registerPwa();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <DialogProvider>
          <App />
        </DialogProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
);
