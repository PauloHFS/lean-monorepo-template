import { expect, type Page, test } from '@playwright/test'

import { mockJson, mockUnauthenticated } from './helpers'

/**
 * Falhas de autenticação: tudo mockado via page.route, sem backend/DB.
 * O AuthProvider chama /auth/me no mount; mockamos 401 para partir de "deslogado".
 */

test.beforeEach(async ({ page }) => {
  await mockUnauthenticated(page)
})

async function submitCredentials(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill('user@example.com')
  await page.getByLabel('Senha').fill('supersecret123')
  await page.getByRole('button', { name: /entrar/i }).click()
}

test('credenciais inválidas mostram alerta 401', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 401, { detail: 'invalid credentials' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('401')
  await expect(alert).toContainText('invalid credentials')
})

test('rate limit mostra alerta 429', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 429, { detail: 'rate limit exceeded' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('429')
  await expect(alert).toContainText('rate limit exceeded')
})

test('usuário inativo mostra alerta 403', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 403, { detail: 'user inactive' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('403')
  await expect(alert).toContainText('user inactive')
})

test('falha de rede mostra erro no alerta', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) => route.abort())

  await submitCredentials(page)

  // fetch rejeitado (TypeError) cai no humanizeError como "Failed to fetch".
  await expect(page.getByRole('alert')).toContainText(/failed to fetch/i)
})

test('código 2FA inválido mostra alerta 401', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 200, {
      requires_2fa: true,
      pending_token: 'pending-123',
      methods: ['totp'],
    }),
  )
  await page.route('**/api/v1/auth/2fa/verify', (route) =>
    mockJson(route, 401, { detail: 'invalid 2fa code' }),
  )

  await submitCredentials(page)

  await page.getByLabel('Código').fill('123456')
  await page.getByRole('button', { name: /verificar/i }).click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('401')
  await expect(alert).toContainText('invalid 2fa code')
})

test('sessão ausente manda /dashboard para /login', async ({ page }) => {
  await page.goto('/dashboard')

  await expect(page).toHaveURL(/\/login$/)
})
