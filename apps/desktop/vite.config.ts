import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import path from 'path'

export default defineConfig({
  base: './',
  plugins: [
    react(),
    electron([
      {
        entry: 'electron/main.ts',
        onstart(options) {
          options.reload()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              // `electron` is always external. `electron-updater` must stay
              // external too: it reads its own package.json + app-update.yml
              // and require()s electron internals, so it cannot be bundled.
              // electron-builder ships it (the sole production dependency)
              // into the asar's node_modules, where this require resolves.
              external: ['electron', 'electron-updater'],
            },
          },
        },
      },
    ]),
    renderer(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../../packages/shared-types/src'),
    },
  },
  css: {
    postcss: './postcss.config.js',
  },
})
