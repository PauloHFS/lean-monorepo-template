import { type APIRequestContext, expect, test } from '@playwright/test'

import {
  composeAvailable,
  execInPostgres,
  loginViaApiContainer,
  resetLoginBuckets,
  resetRegisterBuckets,
  sqlLiteral,
  waitForBackend,
} from './db'

/**
 * Infra real (API + Postgres + worker). Cada caso pula quando a stack não está
 * no ar. Os logins daqui acontecem DENTRO do container da API (IP 127.0.0.1),
 * então o bucket de 5/60s do IP do host — já saturado pelos specs existentes —
 * fica intocado.
 */

// Admin determinístico semeado pelo `just e2e-full`.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'e2e-admin-password-123'
const PASSWORD = 'supersecret123'

let stackProbe: Promise<boolean> | undefined

/** Probe único por arquivo: 15s de tolerância para a API subindo no e2e-full. */
function stackReady(request: APIRequestContext): Promise<boolean> {
  stackProbe ??= (async () => {
    if (!(await composeAvailable())) return false
    const ready = await waitForBackend(request)
    // O bucket de register por IP é 10/60s e compartilhado pela suíte: zera
    // para este arquivo não depender do que rodou antes (o R3 cadastra 4x).
    if (ready) await resetRegisterBuckets().catch(() => undefined)
    return ready
  })()
  return stackProbe
}

function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
}

function cookieHeader(cookieName: string, token: string): Record<string, string> {
  return { Cookie: `${cookieName}=${token}` }
}

test('R2 — o worker consome o job de e-mail enfileirado', async ({ request }) => {
  test.setTimeout(60_000)
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres/worker fora do ar)')

  // O enqueue tem rate limit por IP (5/60s); zera para o teste ser repetível.
  await execInPostgres("DELETE FROM rate_limits WHERE key LIKE '%:users.enqueue_email'")

  // Login no container: bucket do host (5/60s) não é consumido.
  await resetLoginBuckets()
  const { cookieName, token } = await loginViaApiContainer(ADMIN_EMAIL, ADMIN_PASSWORD)
  const recipient = uniqueEmail('e2e-worker')

  const res = await request.post('/api/v1/users/enqueue-email', {
    headers: cookieHeader(cookieName, token),
    data: { to: recipient, subject: 'e2e worker', body: 'prova de consumo pelo worker' },
  })
  expect(res.status()).toBe(202)
  const body = (await res.json()) as { job_id: number; status: string }
  expect(body.status).toBe('queued')
  const jobId = body.job_id
  expect(Number.isInteger(jobId)).toBe(true)

  // Sair de `todo`/`doing` para um estado terminal prova que o WORKER pegou o
  // job — o 202 da API sozinho não prova nada. O Mailpit fica no profile
  // `dev` e não sobe no e2e-full, então o SMTP falha, há 3 retries e o job
  // termina `failed` com uma linha em dead_letters.
  await expect
    .poll(
      async () =>
        (await execInPostgres(`SELECT status FROM procrastinate_jobs WHERE id = ${jobId}`)).trim(),
      { timeout: 30_000, intervals: [250, 500, 1000] },
    )
    .toMatch(/^(succeeded|failed)$/)

  const status = (
    await execInPostgres(`SELECT status FROM procrastinate_jobs WHERE id = ${jobId}`)
  ).trim()

  if (status === 'failed') {
    // Caminho retry -> DLQ: exatamente uma linha para este job.
    const deadLetters = (
      await execInPostgres(`SELECT count(*) FROM dead_letters WHERE original_job_id = ${jobId}`)
    ).trim()
    expect(deadLetters).toBe('1')
  }
})

test('R3 — rate limit real: 4º register do mesmo e-mail responde 429', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  // E-mail novo por execução => bucket POR CONTA do register nasce frio.
  // enforce_account_limit("register", email, 3/3600) roda ANTES do insert,
  // então os dois 409 também contam; a 4ª tentativa vira 429 com
  // Retry-After 3600 (prova de que foi o bucket de conta, não o de IP).
  const email = uniqueEmail('e2e-rate')
  const statuses: number[] = []
  const retryAfter: (string | undefined)[] = []

  for (let attempt = 0; attempt < 4; attempt += 1) {
    const res = await request.post('/api/v1/auth/register', {
      data: { email, password: PASSWORD, full_name: 'E2E Rate' },
    })
    statuses.push(res.status())
    retryAfter.push(res.headers()['retry-after'])
  }

  expect(statuses).toEqual([201, 409, 409, 429])
  expect(retryAfter[3]).toBe('3600')

  // Limpeza: o usuário criado na 1ª tentativa e o contador por conta.
  await execInPostgres(`DELETE FROM users WHERE email = ${sqlLiteral(email)}`)
  await execInPostgres(
    `DELETE FROM rate_limits WHERE key = ${sqlLiteral(`acct:register:${email}`)}`,
  )
})

test('R4 — sessão expirada responde 401 (com controle 200 e logout revogando)', async ({
  request,
}) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const email = uniqueEmail('e2e-expired')
  const reg = await request.post('/api/v1/auth/register', {
    data: { email, password: PASSWORD, full_name: 'E2E Expired' },
  })
  expect(reg.status()).toBe(201)

  // Login no container (bucket do host intocado).
  await resetLoginBuckets()
  const expired = await loginViaApiContainer(email, PASSWORD)

  // Expira APENAS as sessões deste usuário novo — nunca um UPDATE global.
  await execInPostgres(
    "UPDATE sessions SET expires_at = now() - interval '1 minute' " +
      `WHERE user_id = (SELECT id FROM users WHERE email = ${sqlLiteral(email)})`,
  )

  const meExpired = await request.get('/api/v1/auth/me', {
    headers: cookieHeader(expired.cookieName, expired.token),
  })
  expect(meExpired.status()).toBe(401)
  const expiredBody = (await meExpired.json()) as { detail?: string }
  expect(expiredBody.detail).toBe('expired session')

  // CONTROLE: sessão nova do mesmo usuário responde 200 com o e-mail certo.
  // Sem isso o 401 acima poderia ser só cookie quebrado.
  const control = await loginViaApiContainer(email, PASSWORD)
  const meOk = await request.get('/api/v1/auth/me', {
    headers: cookieHeader(control.cookieName, control.token),
  })
  expect(meOk.status()).toBe(200)
  expect(((await meOk.json()) as { email?: string }).email).toBe(email)

  // Bônus: logout revoga o cookie (replay depois do logout -> 401).
  const logout = await request.post('/api/v1/auth/logout', {
    headers: cookieHeader(control.cookieName, control.token),
  })
  expect(logout.status()).toBe(204)
  const replay = await request.get('/api/v1/auth/me', {
    headers: cookieHeader(control.cookieName, control.token),
  })
  expect(replay.status()).toBe(401)

  // Limpeza: o usuário (sessions têm ON DELETE CASCADE) e os buckets da conta.
  await execInPostgres(`DELETE FROM users WHERE email = ${sqlLiteral(email)}`)
  await execInPostgres(
    `DELETE FROM rate_limits WHERE key IN (${sqlLiteral(`acct:register:${email}`)}, ` +
      `${sqlLiteral(`acct:login:${email}`)})`,
  )
})
