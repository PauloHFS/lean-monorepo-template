import { defineConfig, devices } from '@playwright/test'

/**
 * E2E padrão: front em :5173 (Vite dev server) + API em :8000 (proxy /api do Vite).
 * Os specs mockados sobem o Vite sozinhos e interceptam /api via page.route.
 * Os specs de backend real skipam quando /api/v1/healthz não responde.
 *
 * Para apontar para a SPA servida pela API (ex.: stack Docker): E2E_BASE_URL=http://localhost:8000
 */
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const useViteServer = baseURL.includes(':5173')

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false, // 1 teste por vez; melhor pra dev local
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL,
    trace: 'on-first-retry',
    headless: true,
  },
  // Só sobe o Vite quando o alvo é o dev server; se a SPA vem da API, não há o que subir.
  webServer: useViteServer
    ? {
        command: 'npm run dev',
        url: 'http://localhost:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
