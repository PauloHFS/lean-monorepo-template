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
  await page.getByRole('button', { name: /^entrar$/i }).click()
}

test('credenciais inválidas mostram erro em PT-BR', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 401, { detail: 'invalid credentials' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText(/e-mail ou senha incorretos/i)
})

test('rate limit mostra mensagem de espera', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 429, { detail: 'rate limit exceeded' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText(/muitas tentativas/i)
})

test('usuário inativo mostra mensagem de acesso negado', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 403, { detail: 'user inactive' }),
  )

  await submitCredentials(page)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText(/inativa ou sem permissão/i)
})

test('falha de rede mostra erro de conexão', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) => route.abort())

  await submitCredentials(page)

  await expect(page.getByRole('alert')).toContainText(/não foi possível conectar/i)
})

test('código 2FA inválido mostra erro em PT-BR', async ({ page }) => {
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
  await expect(alert).toContainText(/código inválido ou expirado/i)
})

test('sessão ausente manda /dashboard para /login', async ({ page }) => {
  await page.goto('/dashboard')

  await expect(page).toHaveURL(/\/login$/)
})

test('sessão ausente manda /security para /login', async ({ page }) => {
  await page.goto('/security')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: /autenticador \(totp\)/i })).toHaveCount(0)
})

test('guard preserva o destino e o login retorna para ele', async ({ page }) => {
  await page.route('**/api/v1/auth/login', (route) =>
    mockJson(route, 200, {
      requires_2fa: false,
      user: {
        id: '00000000-0000-0000-0000-000000000001',
        email: 'user@example.com',
        full_name: 'User',
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route('**/api/v1/auth/me', (route) =>
    mockJson(route, 401, { detail: 'not authenticated' }),
  )
  await page.route('**/api/v1/healthz', (route) => mockJson(route, 200, { status: 'ok', db: true }))
  await page.route('**/api/v1/auth/2fa/status', (route) =>
    mockJson(route, 200, {
      totp_enabled: false,
      totp_confirmed_at: null,
      recovery_codes_remaining: 0,
      passkeys: [],
    }),
  )

  await page.goto('/security')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('E-mail').fill('user@example.com')
  await page.getByLabel('Senha').fill('supersecret123')
  await page.getByRole('button', { name: /^entrar$/i }).click()

  await expect(page).toHaveURL(/\/security$/)
})
