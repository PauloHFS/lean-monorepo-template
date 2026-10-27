import {
  type APIRequestContext,
  type BrowserContext,
  type CDPSession,
  expect,
  type Page,
  test,
} from '@playwright/test'

import {
  composeAvailable,
  execInApi,
  loginViaApiContainer,
  resetLoginBuckets,
  resetRegisterBuckets,
  sessionCookie,
  waitForBackend,
} from './db'

/**
 * Passkey real (API + Postgres + WebAuthn): registra uma credencial pelo UI,
 * prova que o login por passkey cria uma sessão de verdade e que uma passkey de
 * outro usuário não autentica a conta da vítima.
 *
 * O backend valida `expected_origin === settings.web_origin` (exato), então a
 * cerimônia só é aceita com a página em http://localhost:5173. O `just e2e-full`
 * serve a SPA em :8000 e por isso pula aqui; o Vite em :5173 proxia /api → :8000.
 *
 * A autenticação virtual vem do CDP do Chromium (WebAuthn domain), não de mock:
 * o attestation `none` e a assertion são gerados pelo browser e verificados
 * pela API real.
 */

// Default de `SESSION_COOKIE_NAME` (Settings); mesma constante de twofa-flow.
const SESSION_COOKIE = 'lm_session'
const VITE_ORIGIN = 'http://localhost:5173'

// `password_min_length` default é 8.
const PASSWORD = 'supersecret123'

interface VirtualAuthenticator {
  cdp: CDPSession
  id: string
}

/**
 * Registra um autenticador virtual no Chromium. `automaticPresenceSimulation`
 * é obrigatório: sem ele a cerimônia espera um toque que nunca acontece e o
 * backend rejeitaria `flags.up == false`.
 */
async function addVirtualAuthenticator(cdp: CDPSession): Promise<VirtualAuthenticator> {
  await cdp.send('WebAuthn.enable')
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  })
  return { cdp, id: authenticatorId }
}

/**
 * Condições da cerimônia. `test.skip` dentro do helper é propagado pelo
 * Playwright para o teste corrente; o retorno nunca é usado quando o teste pula.
 */
async function skipUnlessCeremonyIsPossible(
  request: APIRequestContext,
  page: Page,
  context: BrowserContext,
): Promise<CDPSession | undefined> {
  test.skip(
    test.info().project.use.baseURL !== VITE_ORIGIN,
    `WebAuthn exige origin ${VITE_ORIGIN} (WEB_ORIGIN); baseURL atual não serve`,
  )
  test.skip(!(await composeAvailable()), 'stack compose indisponível (API/Postgres fora do ar)')
  test.skip(!(await waitForBackend(request)), 'API indisponível')

  // O stack valida a origin contra o próprio WEB_ORIGIN: se o .env local
  // apontar para outra origin, a cerimônia é impossível (e não um bug do app).
  const webOrigin = (
    await execInApi('from app.core.config import settings\nprint(settings.web_origin)', [])
  ).trim()
  test.skip(
    webOrigin !== VITE_ORIGIN,
    `WEB_ORIGIN do stack é ${webOrigin}; a cerimônia exige ${VITE_ORIGIN}`,
  )

  const cdp = await context.newCDPSession(page).catch(() => undefined)
  test.skip(!cdp, 'CDP indisponível (virtual authenticator só no Chromium)')
  return cdp
}

/** Usuário descartável com e-mail único por execução. */
async function registerUser(request: APIRequestContext): Promise<string> {
  const email = `e2e-passkey-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`
  const res = await request.post('/api/v1/auth/register', {
    data: { email, password: PASSWORD, full_name: 'E2E Passkey' },
  })
  expect(res.status()).toBe(201)
  return email
}

/**
 * Sessão de setup vinda de um login DENTRO do container (IP 127.0.0.1), fora do
 * bucket de 5/60s do host. O cadastro em si usa o IP do host (bucket zerado no
 * beforeAll).
 */
async function signInAs(context: BrowserContext, email: string): Promise<void> {
  const { cookieName, token } = await loginViaApiContainer(email, PASSWORD)
  expect(cookieName).toBe(SESSION_COOKIE)
  await context.clearCookies()
  await context.addCookies([sessionCookie(cookieName, token)])
}

/** Registra uma passkey pela tela real (/security → "Registrar passkey"). */
async function registerPasskeyThroughUi(page: Page): Promise<void> {
  await page.goto('/security')
  await expect(page.getByRole('heading', { name: 'Segurança' })).toBeVisible()
  await page.getByRole('button', { name: 'Registrar passkey' }).click()
  await expect(page.getByRole('status')).toContainText('Passkey registrada')
  await expect(page.getByRole('alert')).toHaveCount(0)
}

test.beforeAll(async () => {
  // Buckets de 5 logins/60s e 10 cadastros/60s são compartilhados pelo IP do
  // host e persistem no Postgres; zerar evita 429 herdado de outro spec/run.
  if (!(await composeAvailable())) return
  await resetLoginBuckets().catch(() => undefined)
  await resetRegisterBuckets().catch(() => undefined)
})

test('registro de passkey + login por passkey cria sessão real', async ({
  page,
  context,
  request,
}) => {
  const cdp = await skipUnlessCeremonyIsPossible(request, page, context)
  if (!cdp) return

  // 1. Usuário descartável + sessão de setup (container).
  const email = await registerUser(request)
  await signInAs(context, email)

  // 2. Autenticador virtual ANTES da cerimônia.
  const { cdp: webauthn, id: authenticatorId } = await addVirtualAuthenticator(cdp)

  // 3. Registro pelo UI real.
  await registerPasskeyThroughUi(page)

  // O autenticador virtual realmente guardou a credencial criada pelo browser.
  const stored = await webauthn.send('WebAuthn.getCredentials', { authenticatorId })
  expect(stored.credentials).toHaveLength(1)

  // 4. Logout real pelo UI e novo login: senha → 2FA → "Usar passkey".
  await page.goto('/dashboard')
  await expect(page.getByText(email)).toBeVisible()
  await page.getByRole('button', { name: /^sair$/i }).click()
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha').fill(PASSWORD)
  await page.getByRole('button', { name: /^entrar$/i }).click()

  await expect(page.getByRole('heading', { name: /verificação em duas etapas/i })).toBeVisible()
  // Sem cookie de sessão enquanto o segundo fator não é verificado.
  expect((await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE)).toBeUndefined()

  await page.getByRole('button', { name: /usar passkey/i }).click()

  // 5. Sessão de verdade: cookie HttpOnly, /auth/me e Dashboard.
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByText(email)).toBeVisible()

  const session = (await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE)
  expect(session).toBeTruthy()
  expect(session?.httpOnly).toBe(true)

  const me = await page.request.get('/api/v1/auth/me')
  expect(me.status()).toBe(200)
  const body = (await me.json()) as { email: string }
  expect(body.email).toBe(email)
})

test('passkey de outro usuário não autentica a conta da vítima', async ({
  page,
  context,
  request,
}) => {
  const cdp = await skipUnlessCeremonyIsPossible(request, page, context)
  if (!cdp) return

  // 1. Vítima e atacante, cada um com a própria passkey no mesmo autenticador
  //    virtual (é o credential_id que difere, não o dispositivo).
  const victim = await registerUser(request)
  const attacker = await registerUser(request)
  const { cdp: webauthn, id: authenticatorId } = await addVirtualAuthenticator(cdp)

  await signInAs(context, victim)
  await registerPasskeyThroughUi(page)
  expect(
    (await webauthn.send('WebAuthn.getCredentials', { authenticatorId })).credentials,
  ).toHaveLength(1)

  await signInAs(context, attacker)
  const registerVerify = page.waitForResponse(
    (res) =>
      res.url().endsWith('/api/v1/auth/2fa/passkey/register/verify') &&
      res.request().method() === 'POST',
  )
  await registerPasskeyThroughUi(page)
  const posted = (await (await registerVerify).request().postDataJSON()) as {
    credential?: { id?: string }
  }
  const attackerCredentialId = posted.credential?.id
  if (!attackerCredentialId) throw new Error('registro do atacante sem credential id')

  expect(
    (await webauthn.send('WebAuthn.getCredentials', { authenticatorId })).credentials,
  ).toHaveLength(2)

  // 2. Pending da vítima (único login do host neste teste: a senha dela).
  const login = await request.post('/api/v1/auth/login', {
    data: { email: victim, password: PASSWORD },
  })
  expect(login.status()).toBe(200)
  const pending = (await login.json()) as { requires_2fa?: boolean; pending_token?: string }
  expect(pending.requires_2fa).toBe(true)
  const pendingToken = pending.pending_token
  if (!pendingToken) throw new Error('login da vítima sem pending token')

  const optionsRes = await request.post('/api/v1/auth/2fa/passkey/login/options', {
    data: { pending_token: pendingToken },
  })
  expect(optionsRes.status()).toBe(200)
  const options = (await optionsRes.json()) as {
    options: { challenge: string }
    challenge: string
  }

  // 3. O autenticador assina o challenge DA VÍTIMA com a passkey DO ATACANTE.
  //    (O browser só permitiria isso porque allowCredentials foi montado à mão;
  //    o app nunca pediria a credencial de outro usuário.)
  const assertion = await page.evaluate(
    async ({ challenge, credentialId }: { challenge: string; credentialId: string }) => {
      const decode = (value: string): Uint8Array => {
        const base64 = value.replaceAll('-', '+').replaceAll('_', '/')
        const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
        const binary = atob(padded)
        return Uint8Array.from(binary, (char) => char.charCodeAt(0))
      }
      const toBase64Url = (buffer: ArrayBuffer): string => {
        const binary = Array.from(new Uint8Array(buffer), (byte) => String.fromCharCode(byte)).join(
          '',
        )
        return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
      }

      const credential = await navigator.credentials.get({
        publicKey: {
          challenge: decode(challenge),
          rpId: 'localhost',
          allowCredentials: [{ id: decode(credentialId), type: 'public-key' }],
          userVerification: 'preferred',
        },
      })
      if (!(credential instanceof PublicKeyCredential)) return null

      const response = credential.response
      if (!(response instanceof AuthenticatorAssertionResponse)) return null

      return {
        id: credential.id,
        rawId: toBase64Url(credential.rawId),
        type: 'public-key',
        response: {
          clientDataJSON: toBase64Url(response.clientDataJSON),
          authenticatorData: toBase64Url(response.authenticatorData),
          signature: toBase64Url(response.signature),
          userHandle: response.userHandle ? toBase64Url(response.userHandle) : undefined,
        },
      }
    },
    { challenge: options.options.challenge, credentialId: attackerCredentialId },
  )
  if (!assertion) throw new Error('assertion do atacante não foi produzida')

  // 4. A API confere `credential_id AND user_id`: a assinatura é válida, mas a
  //    credencial não é da vítima → 401. Sem esse predicado sairia sessão da
  //    vítima para o atacante (account takeover).
  const verify = await request.post('/api/v1/auth/2fa/passkey/login/verify', {
    data: { challenge: options.challenge, credential: assertion },
  })
  expect(verify.status()).toBe(401)
  expect(await verify.json()).toMatchObject({ detail: 'no passkey for user' })
})
