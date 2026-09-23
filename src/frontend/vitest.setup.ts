import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

function installStorage(name: 'localStorage' | 'sessionStorage') {
  if (typeof window === 'undefined') return;
  try { if (window[name]) return; } catch { /* Node 24.19 may expose no storage without a file. */ }
  const values = new Map<string, string>();
  Object.defineProperty(window, name, { configurable: true, value: {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => { values.delete(key); },
    setItem: (key: string, value: string) => { values.set(String(key), String(value)); },
  } });
}

installStorage('localStorage');
installStorage('sessionStorage');

afterEach(() => {
  cleanup();
});
