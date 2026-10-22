// The client's tests (H26): the main process's parts run in Node, the screens in jsdom
// (`@vitest-environment jsdom` at the top of their files).
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'node',
    restoreMocks: true,
  },
})
