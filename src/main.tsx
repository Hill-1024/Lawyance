/*
 * 模块描述：前端启动入口，将 React 应用挂载到 DOM 并接入浏览器路由。
 */

import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { DialogProvider } from './contexts/DialogContext';
import { LocaleProvider } from './contexts/LocaleContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { setupNativeChrome } from './lib/native-bootstrap';
import { registerPwa } from './lib/pwa';
import { BASE_PATH } from './lib/app-config';
import './index.css';

setupNativeChrome().catch(console.error);
registerPwa();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
<<<<<<< HEAD
    <BrowserRouter>
      <LocaleProvider>
        <ThemeProvider>
          <DialogProvider>
            <App />
          </DialogProvider>
        </ThemeProvider>
      </LocaleProvider>
=======
    <BrowserRouter basename={BASE_PATH || undefined}>
      <ThemeProvider>
        <DialogProvider>
          <App />
        </DialogProvider>
      </ThemeProvider>
>>>>>>> 55d2921728183769bb93bae063fe5f940965e76b
    </BrowserRouter>
  </StrictMode>,
);
