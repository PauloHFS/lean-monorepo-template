import { expect, test } from '@playwright/test'

import { backendAvailable } from './helpers'

/**
 * Jornada crítica da UI contra o stack real (API + Postgres).
 * - Usuário comum: enqueue-email é superuser-only, então a seção não aparece.
 * - Admin semeado por `just e2e-full`: enfileira e vê o job_id.
 * Sem backend real, cada teste pula.
 */

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'e2e-admin-password-123'

test('registrar → login → usuário comum não vê a seção de job', async ({ page, request }) => {
  const available = await backendAvailable(request)
  test.skip(!available, 'backend real indisponível (API/Postgres fora do ar)')

  const email = `e2e-${Date.now()}@example.com`
  const password = 'supersecret123'

  // 1. Register via API (mais rápido que UI; UI tb testada no smoke)
  const reg = await request.post('/api/v1/auth/register', {
    data: { email, password, full_name: 'E2E User' },
  })
  expect(reg.status()).toBe(201)

  // 2. Login pela UI
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha').fill(password)
  await page.getByRole('button', { name: /^entrar$/i }).click()

  // 3. Cai no /dashboard
  await expect(page).toHaveURL(/\/dashboard$/)

  // 4. Vê a saudação
  await expect(page.getByText(email)).toBeVisible()

  // 5. Usuário comum não recebe a seção superuser-only de enqueue
  await expect(page.getByRole('button', { name: /enfileirar/i })).toBeHidden()
})

test('admin (superuser) → enfileirar job aparece no Dashboard', async ({ page, request }) => {
  const available = await backendAvailable(request)
  test.skip(!available, 'backend real indisponível (API/Postgres fora do ar)')

  // Admin determinístico semeado pelo `just e2e-full`.
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: /^entrar$/i }).click()

  await expect(page).toHaveURL(/\/dashboard$/)

  // Seção visível e enqueue aceito (superuser).
  const enqueueButton = page.getByRole('button', { name: /enfileirar/i })
  await expect(enqueueButton).toBeVisible()
  await enqueueButton.click()

  // A fila é assíncrona; o job_id aparece quando a API responde.
  await expect(page.getByText(/Último job:/)).toBeVisible({ timeout: 10_000 })
})
