import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import './index.css';
import { ToastProvider } from '@/components/ui/Toast';
import { applySettings, readSettings } from '@/lib/settings';
import { applyTheme, readStoredSetting, resolveTheme } from '@/lib/theme';

// Stamp the theme and the Atelier's settings before the first paint, so there
// is no flash of the default accent or of the wrong ground.
applyTheme(resolveTheme(readStoredSetting()));
applySettings(readSettings());

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
);
