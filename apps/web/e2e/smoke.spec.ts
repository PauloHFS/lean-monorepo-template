import { expect, test } from '@playwright/test'

import { backendAvailable, mockUnauthenticated } from './helpers'

/**
 * Smoke: a UI carrega e links básicos funcionam.
 * O healthz só roda com backend real no ar; sem stack, skipa em vez de falhar.
 */
test('app carrega e o formulário de login aparece', async ({ page }) => {
  // Sem backend no CI: mocka 401 para exercitar o caminho "deslogado"
  // (falha de transporte agora vira tela de erro, não logout).
  await mockUnauthenticated(page)

  // 1. UI: home redireciona pra /dashboard, que manda pra /login (não autenticado)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)

  // 2. Login form tem os campos esperados + links de cadastro/recuperação/passkey
  await expect(page.getByLabel('E-mail')).toBeVisible()
  await expect(page.getByRole('button', { name: /enviar código/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /entrar com passkey/i })).toBeVisible()
  await page.getByRole('button', { name: /entrar com senha/i }).click()
  await expect(page.getByLabel('Senha')).toBeVisible()
  await expect(page.getByRole('button', { name: /^entrar$/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /criar conta/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /esqueceu a senha/i })).toBeVisible()
})

test('página de cadastro (/register) e recuperação (/forgot-password) carregam', async ({
  page,
}) => {
  await mockUnauthenticated(page)

  await page.goto('/register')
  await expect(page.getByRole('heading', { name: /criar conta/i })).toBeVisible()
  await expect(page.getByLabel('E-mail')).toBeVisible()
  await expect(page.getByLabel('Senha', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Confirmar senha')).toBeVisible()

  await page.goto('/forgot-password')
  await expect(page.getByRole('heading', { name: /recuperar senha/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /enviar link/i })).toBeVisible()
})

test('healthz responde', async ({ request }) => {
  const available = await backendAvailable(request)
  test.skip(!available, 'backend real indisponível (API/Postgres fora do ar)')

  // /api/v1/healthz retorna { status: "ok", db: true } (ou degraded)
  const res = await request.get('/api/v1/healthz')
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(['ok', 'degraded']).toContain(body.status)
  expect(body.db).toBeDefined()
})

test('404 renderiza a página NotFound', async ({ page }) => {
  await mockUnauthenticated(page)
  await page.goto('/rota-que-nao-existe')

  // App.tsx: rota "*" renderiza <NotFound>, sem redirect.
  await expect(page.getByRole('heading', { name: /página não encontrada/i })).toBeVisible()
  await expect(page).toHaveURL(/\/rota-que-nao-existe$/)
})
