import { type BrowserContext, expect, type Page, test } from '@playwright/test'

import { backendAvailable } from './helpers'
import { generateTotp, RFC6238_VECTOR } from './totp'

/**
 * 2FA real (API + Postgres), não mockado:
 * configurar TOTP, deslogar e provar que o login com TOTP e com recovery code
 * cria uma sessão de verdade (cookie HttpOnly + /auth/me + Dashboard).
 *
 * Sem backend no ar, o teste pula (padrão de smoke.spec.ts).
 */

// Default de `SESSION_COOKIE_NAME` (Settings); o stack e2e não sobrescreve.
const SESSION_COOKIE = 'lm_session'

async function submitCredentials(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha').fill(password)
  await page.getByRole('button', { name: /^entrar$/i }).click()
}

async function expectRealSession(
  page: Page,
  context: BrowserContext,
  email: string,
): Promise<void> {
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByText(email)).toBeVisible()

  const session = (await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE)
  expect(session).toBeTruthy()
  expect(session?.httpOnly).toBe(true)

  const me = await page.request.get('/api/v1/auth/me')
  expect(me.status()).toBe(200)
  const body = (await me.json()) as { email: string }
  expect(body.email).toBe(email)
}

test('helper TOTP reproduz o vetor da RFC 6238', () => {
  expect(generateTotp(RFC6238_VECTOR.secret, RFC6238_VECTOR.atMs)).toBe(RFC6238_VECTOR.code)
})

test('login com 2FA real: TOTP e recovery code criam sessão', async ({
  page,
  context,
  request,
}) => {
  const available = await backendAvailable(request)
  test.skip(!available, 'backend real indisponível (API/Postgres fora do ar)')

  const email = `e2e-2fa-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
  const password = 'supersecret123'

  // 1. Usuário descartável (e-mail único por execução).
  const reg = await request.post('/api/v1/auth/register', {
    data: { email, password, full_name: 'E2E 2FA' },
  })
  expect(reg.status()).toBe(201)

  // 2. Login inicial (ainda sem 2FA) só para configurar o TOTP. Feito pela API
  //    para não consumir o bucket de 5 logins/60s por IP com a UI.
  const initial = await request.post('/api/v1/auth/login', { data: { email, password } })
  expect(initial.status()).toBe(200)
  expect(((await initial.json()) as { requires_2fa: boolean }).requires_2fa).toBe(false)

  // 3. Setup + confirm: o segredo e os recovery codes vêm da API real.
  const setup = await request.post('/api/v1/auth/2fa/totp/setup')
  expect(setup.status()).toBe(200)
  const { secret } = (await setup.json()) as { secret: string }

  const confirm = await request.post('/api/v1/auth/2fa/totp/confirm', {
    data: { code: generateTotp(secret) },
  })
  expect(confirm.status()).toBe(200)
  const { recovery_codes } = (await confirm.json()) as { recovery_codes: string[] }
  expect(recovery_codes.length).toBeGreaterThan(0)

  // 4. Logout (consome a sessão usada no setup).
  expect((await request.post('/api/v1/auth/logout')).status()).toBe(204)

  // 5. Login pela UI: senha → tela de 2FA (sem cookie ainda) → TOTP.
  await submitCredentials(page, email, password)
  await expect(page.getByRole('heading', { name: /verificação em duas etapas/i })).toBeVisible()

  const pendingCookies = (await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE)
  expect(pendingCookies).toBeUndefined()

  await page.getByLabel('Código').fill(generateTotp(secret))
  await page.getByRole('button', { name: /verificar/i }).click()
  await expectRealSession(page, context, email)

  // 6. Segundo cenário: logout + login + recovery code.
  await page.getByRole('button', { name: /^sair$/i }).click()
  await expect(page).toHaveURL(/\/login$/)

  await submitCredentials(page, email, password)
  await expect(page.getByRole('heading', { name: /verificação em duas etapas/i })).toBeVisible()

  await page.getByLabel('Código').fill(recovery_codes[0])
  await page.getByRole('button', { name: /verificar/i }).click()
  await expectRealSession(page, context, email)
})
