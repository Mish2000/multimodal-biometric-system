// The client's build (H4, H26): the main process, its sandboxed preload and the React renderer.
import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'electron-vite'

export default defineConfig({
  main: {
    build: {
      rollupOptions: {
        // The bridge and the window's security are entries of their own, so automated checks can load
        // them without the app's window.
        input: {
          index: resolve(import.meta.dirname, 'src/main/index.ts'),
          bridge: resolve(import.meta.dirname, 'src/main/bridge.ts'),
          window: resolve(import.meta.dirname, 'src/main/window.ts'),
        },
      },
    },
  },
  preload: {
    build: {
      // A sandboxed preload runs as a classic script, so it is built as CommonJS.
      rollupOptions: { output: { format: 'cjs' } },
    },
  },
  renderer: {
    plugins: [react()],
  },
})
