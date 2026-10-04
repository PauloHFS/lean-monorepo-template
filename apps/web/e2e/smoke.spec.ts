import { expect, test } from '@playwright/test'

/**
 * Smoke: a UI carrega, links básicos funcionam, o /api/v1/healthz responde.
 * Cobre "o servidor subiu?" — primeira linha de defesa de regressão.
 */
test('app carrega e healthz responde', async ({ page, request }) => {
  // 1. UI: home redireciona pra /dashboard, que manda pra /login (não autenticado)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)

  // 2. Login form tem os campos esperados
  await expect(page.getByLabel('E-mail')).toBeVisible()
  await expect(page.getByLabel('Senha')).toBeVisible()
  await expect(page.getByRole('button', { name: /entrar/i })).toBeVisible()

  // 3. /api/v1/healthz retorna { status: "ok", db: true } (ou degraded)
  const res = await request.get('/api/v1/healthz')
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(['ok', 'degraded']).toContain(body.status)
  expect(body.db).toBeDefined()
})

test('404 serve a SPA (rotas desconhecidas voltam ao login) ', async ({ page }) => {
  await page.goto('/rota-que-nao-existe')
  // SPA fallback manda index.html, que carrega React, que cai no <Navigate> pra /login
  await expect(page).toHaveURL(/\/login$/)
})
