import { expect, test } from '@playwright/test'

import { mockAuthenticated, mockHealth, mockJson, mockUser } from './helpers'

/**
 * Fluxo assíncrono do enqueue de e-mail, mockado via page.route.
 * O Dashboard exige sessão: mockamos /auth/me autenticado + healthz.
 */
test.beforeEach(async ({ page }) => {
  await mockAuthenticated(page)
  await mockHealth(page)
})

test('enqueue com sucesso exibe o job id', async ({ page }) => {
  await page.route('**/api/v1/users/enqueue-email', (route) =>
    mockJson(route, 202, { job_id: 42, status: 'queued' }),
  )

  await page.goto('/dashboard')
  await expect(page.getByText(mockUser.email)).toBeVisible()

  await page.getByRole('button', { name: /enfileirar/i }).click()

  const lastJob = page.getByText(/Último job:/)
  await expect(lastJob).toBeVisible()
  await expect(lastJob).toContainText('42')
  await expect(lastJob).toContainText('queued')
})

test('enqueue com erro abre alerta nativo', async ({ page }) => {
  await page.route('**/api/v1/users/enqueue-email', (route) =>
    mockJson(route, 500, { detail: 'internal error' }),
  )

  await page.goto('/dashboard')
  await expect(page.getByText(mockUser.email)).toBeVisible()

  const dialogPromise = page.waitForEvent('dialog')
  await page.getByRole('button', { name: /enfileirar/i }).click()
  const dialog = await dialogPromise

  expect(dialog.message()).toContain('500')
  expect(dialog.message()).toContain('internal error')
  await dialog.dismiss()

  // Sem "Último job" quando a chamada falha.
  await expect(page.getByText(/Último job:/)).toHaveCount(0)
})
