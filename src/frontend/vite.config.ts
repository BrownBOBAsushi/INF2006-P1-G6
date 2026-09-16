import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Fixture startup is compiled out of every production build, even --mode mock.
export default defineConfig(({ command, mode }) => ({
  plugins: [react(), {
    name: 'exclude-fixtures-from-build',
    generateBundle(_options, bundle) {
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue;
        for (const id of Object.keys(output.modules)) {
          if (/[/\\](dev|fixtures|__tests__)[/\\]/.test(id) || /\.test\.[tj]sx?$/.test(id)) {
            this.error('Production bundle contains a development fixture or test module.');
          }
        }
      }
    },
  }],
  define: { __MOCK__: JSON.stringify(command === 'serve' && mode === 'mock') },
  server: {
    host: 'localhost', port: 8080, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { sourcemap: false },
  test: {
    globals: true, environment: 'jsdom', setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'], restoreMocks: true,
  },
}));
