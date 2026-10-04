import { defineConfig, devices } from "@playwright/test";

/**
 * Roda E2E contra a stack local: front em :5173 (Vite dev server) + API em :8000.
 * O Vite proxy /api -> :8000 já está configurado.
 *
 * Requisitos: `just up` (sobe Postgres) + `just api-run` + `just worker-run`
 *            OU `just init` (sobe tudo via Docker).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,    // 1 teste por vez; melhor pra dev local
  workers: 1,
  reporter: "list",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});