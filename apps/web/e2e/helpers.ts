import type { APIRequestContext, Page, Route } from '@playwright/test'

/**
 * Usuário fake para os specs que mockam a sessão.
 * Superuser porque o fluxo mockado do Dashboard exercita a seção de enqueue,
 * que a API restringe a superuser.
 */
export const mockUser = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'e2e-mock@example.com',
  full_name: 'E2E Mock',
  is_active: true,
  is_superuser: true,
}

export const mockPolicy = {
  actor: { id: mockUser.id, role: 'admin' },
  rules: [
    { resource: 'user', action: 'list', fields: null, when: { kind: 'always' } },
    { resource: 'user', action: 'read', fields: null, when: { kind: 'always' } },
    { resource: 'user', action: 'delete', fields: null, when: { kind: 'always' } },
    { resource: 'user', action: 'update', fields: ['full_name'], when: { kind: 'always' } },
    {
      resource: 'user',
      action: 'update',
      fields: ['is_active', 'is_superuser'],
      when: {
        kind: 'not',
        cond: {
          kind: 'eq',
          left: { kind: 'ref', scope: 'resource', attr: 'id' },
          right: { kind: 'ref', scope: 'actor', attr: 'id' },
        },
      },
    },
    { resource: 'email', action: 'create', fields: null, when: { kind: 'always' } },
  ],
}

/** true se a API real responde /api/v1/healthz em ~2s. Nunca lança. */
export async function backendAvailable(request: APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get('/api/v1/healthz', { timeout: 2_000 })
    return res.ok()
  } catch {
    return false
  }
}

/** Fulfill com JSON, sem repetir headers em cada spec. */
export async function mockJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/** Sessão ausente: /auth/me devolve 401 e a UI cai no /login. */
export function mockUnauthenticated(page: Page): Promise<void> {
  return page.route('**/api/v1/auth/me', (route) =>
    mockJson(route, 401, { detail: 'not authenticated' }),
  )
}

/** Sessão autenticada: /auth/me devolve o usuário fake (libera o Dashboard). */
export async function mockAuthenticated(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/me', (route) => mockJson(route, 200, mockUser))
  await page.route('**/api/v1/users?**', (route) => mockJson(route, 200, [mockUser]))
  await page.route('**/api/v1/permissions/me', (route) => mockJson(route, 200, mockPolicy))
}

/** Healthz mockado para o card "Saúde do sistema" do Dashboard. */
export function mockHealth(page: Page): Promise<void> {
  return page.route('**/api/v1/healthz', (route) =>
    mockJson(route, 200, { status: 'ok', db: true }),
  )
}
