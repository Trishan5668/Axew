import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

<<<<<<< HEAD
// Standalone Vitest config — intentionally does NOT load vite-plugin-electron
// so the test runner stays a pure jsdom/React environment.
=======
>>>>>>> 1267c0e (v1.1)
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../../packages/shared-types/src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
<<<<<<< HEAD
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
=======
    setupFiles: ['./src/tests/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
>>>>>>> 1267c0e (v1.1)
  },
})
