import {
  type APIRequestContext,
  expect,
  request as playwrightRequest,
  test,
} from '@playwright/test'

import type { UserOut } from '../src/api/types'
import {
  composeAvailable,
  loginViaApiContainer,
  resetRegisterBuckets,
  sessionCookie,
  waitForBackend,
} from './db'

/**
 * Superfície da API que ainda não tinha e2e real (API + Postgres).
 * Tudo aqui é chamada HTTP: livez, users (list/me/delete) e enqueue-email.
 *
 * Sessões são contextos dedicados (`playwrightRequest.newContext`), então cada
 * identidade tem o próprio cookie jar e não vaza estado entre os testes.
 * Os logins acontecem DENTRO do container da API (IP 127.0.0.1), então o bucket
 * de 5/60s do IP do host — usado pelos specs de browser — fica intocado.
 * Sem a stack no ar, cada teste pula.
 */

// Admin determinístico semeado pelo `just e2e-full`.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'e2e-admin-password-123'

// `password_min_length` default é 8; sem 2FA para o login emitir cookie direto.
const PASSWORD = 'supersecret123'

interface RegisteredUser {
  id: string
  email: string
  password: string
}

// Sessões compartilhadas: uma de admin e uma de usuário comum por arquivo.
// Criadas sob demanda — cada teste continua válido sozinho.
let adminSession: APIRequestContext | undefined
let normalUser: RegisteredUser | undefined
let normalSession: APIRequestContext | undefined
let stackProbe: Promise<boolean> | undefined

function newContext(): Promise<APIRequestContext> {
  return playwrightRequest.newContext({ baseURL: test.info().project.use.baseURL })
}

/** Probe único por arquivo: compose no ar E API respondendo (tolera boot lento). */
function stackReady(request: APIRequestContext): Promise<boolean> {
  stackProbe ??= (async () => {
    if (!(await composeAvailable())) return false
    const ready = await waitForBackend(request)
    // Bucket de register por IP é 10/60s e compartilhado pela suíte: este
    // arquivo cadastra 4 usuários, então zera antes de começar.
    if (ready) await resetRegisterBuckets().catch(() => undefined)
    return ready
  })()
  return stackProbe
}

/** Registra um usuário descartável com e-mail único por execução. */
async function registerUser(): Promise<RegisteredUser> {
  const email = `e2e-api-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
  const ctx = await newContext()
  try {
    const res = await ctx.post('/api/v1/auth/register', {
      data: { email, password: PASSWORD, full_name: 'E2E API' },
    })
    expect(res.status()).toBe(201)
    const body = (await res.json()) as UserOut
    return { id: body.id, email, password: PASSWORD }
  } finally {
    await ctx.dispose()
  }
}

/**
 * Login real no container da API + contexto Playwright com o cookie de sessão.
 * Não usa o bucket `{ip_do_host}:auth.login` (5/60s) dos specs de browser.
 */
async function loginAs(email: string, password: string): Promise<APIRequestContext> {
  const { cookieName, token } = await loginViaApiContainer(email, password)
  return playwrightRequest.newContext({
    baseURL: test.info().project.use.baseURL,
    storageState: { cookies: [sessionCookie(cookieName, token)], origins: [] },
  })
}

async function getAdminSession(): Promise<APIRequestContext> {
  adminSession ??= await loginAs(ADMIN_EMAIL, ADMIN_PASSWORD)
  return adminSession
}

/** Usuário comum (não-superuser) reaproveitado pelos casos de 403/me. */
async function getNormalSession(): Promise<{ user: RegisteredUser; session: APIRequestContext }> {
  normalUser ??= await registerUser()
  normalSession ??= await loginAs(normalUser.email, normalUser.password)
  return { user: normalUser, session: normalSession }
}

test.afterAll(async () => {
  // Limpeza do usuário compartilhado; alvos já são apagados em cada teste.
  if (normalUser && adminSession) {
    await adminSession.delete(`/api/v1/users/${normalUser.id}`)
  } else if (normalUser && normalSession) {
    await normalSession.delete(`/api/v1/users/${normalUser.id}`)
  }
  await normalSession?.dispose()
  await adminSession?.dispose()
})

test('GET /livez responde 200 sem sessão', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const res = await request.get('/api/v1/livez')
  expect(res.status()).toBe(200)
  expect(await res.json()).toEqual({ status: 'ok' })
})

test('GET /users como admin lista o admin semeado', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const admin = await getAdminSession()
  const res = await admin.get('/api/v1/users')
  expect(res.status()).toBe(200)

  const users = (await res.json()) as UserOut[]
  expect(users.map((user) => user.email)).toContain(ADMIN_EMAIL)
})

test('GET /users como usuário comum responde 403', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const { session } = await getNormalSession()
  const res = await session.get('/api/v1/users')
  expect(res.status()).toBe(403)
})

test('GET /users/me devolve o próprio e-mail', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const { user, session } = await getNormalSession()
  const res = await session.get('/api/v1/users/me')
  expect(res.status()).toBe(200)

  const body = (await res.json()) as UserOut
  expect(body.email).toBe(user.email)
})

test('DELETE /users/{id} do próprio usuário apaga a conta e invalida a sessão', async ({
  request,
}) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  // Conta descartável: o alvo do delete é o próprio caller.
  const target = await registerUser()
  const session = await loginAs(target.email, target.password)
  try {
    const del = await session.delete(`/api/v1/users/${target.id}`)
    expect(del.status()).toBe(204)

    // ON DELETE CASCADE derruba as sessões; o cookie antigo vira 401.
    const me = await session.get('/api/v1/auth/me')
    expect(me.status()).toBe(401)
  } finally {
    await session.dispose()
  }
})

test('DELETE /users/{id} de outro usuário como admin responde 204', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const target = await registerUser()
  const admin = await getAdminSession()

  const del = await admin.delete(`/api/v1/users/${target.id}`)
  expect(del.status()).toBe(204)
})

test('DELETE /users/{id} de outro usuário como comum responde 403 e alvo permanece', async ({
  request,
}) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const target = await registerUser()
  const { session } = await getNormalSession()
  const admin = await getAdminSession()

  const forbidden = await session.delete(`/api/v1/users/${target.id}`)
  expect(forbidden.status()).toBe(403)

  // Prova que o 403 não apagou nada: o alvo ainda aparece na lista do admin.
  const list = await admin.get('/api/v1/users?limit=100')
  expect(list.status()).toBe(200)
  const emails = ((await list.json()) as UserOut[]).map((user) => user.email)
  expect(emails).toContain(target.email)

  // Limpeza do alvo (o próprio teste criou).
  expect((await admin.delete(`/api/v1/users/${target.id}`)).status()).toBe(204)
})

test('POST /users/enqueue-email como usuário comum responde 403', async ({ request }) => {
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  const { user, session } = await getNormalSession()
  const res = await session.post('/api/v1/users/enqueue-email', {
    data: { to: user.email, subject: 'e2e api surface', body: 'não deve enfileirar' },
  })
  expect(res.status()).toBe(403)
})
