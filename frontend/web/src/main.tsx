import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import './index.css';
import { applyTheme, readStoredSetting, resolveTheme } from '@/lib/theme';

// Stamp the theme before the first paint so there is no light-mode flash.
applyTheme(resolveTheme(readStoredSetting()));

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
