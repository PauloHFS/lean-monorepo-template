import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, Cookie } from '@playwright/test'

import { backendAvailable } from './helpers'

/** Raiz do monorepo: e2e/ -> web/ -> apps/ -> raiz. */
const ROOT = resolve(fileURLToPath(new URL('../../../', import.meta.url)))
const COMPOSE_FILE = resolve(ROOT, 'docker-compose.yml')

/**
 * O `.env` do repo deixa GRAFANA_ADMIN_PASSWORD vazio e o compose usa
 * `${GRAFANA_ADMIN_PASSWORD:?...}`; sem o fallback do justfile QUALQUER
 * comando compose (inclusive `exec`) falha na interpolação.
 */
function composeEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    GRAFANA_ADMIN_PASSWORD: process.env.GRAFANA_ADMIN_PASSWORD || 'validation-only',
  }
}

interface RunResult {
  status: number | null
  stdout: string
  stderr: string
  error: Error | undefined
}

function runCompose(args: string[], input?: string): RunResult {
  const result = spawnSync('docker', ['compose', '-f', COMPOSE_FILE, ...args], {
    cwd: ROOT,
    env: composeEnv(),
    input,
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 10 * 1024 * 1024,
  })

  return {
    status: result.status,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
    error: result.error,
  }
}

function failure(action: string, result: RunResult): Error {
  const detail = result.error?.message ?? result.stderr.trim()
  return new Error(`docker compose ${action} falhou (status ${result.status}): ${detail}`)
}

export function repoRoot(): string {
  return ROOT
}

/** true só quando api E postgres estão rodando. Nunca lança. */
export function composeAvailable(): Promise<boolean> {
  try {
    const result = runCompose(['ps', '--status', 'running', '--services'])
    if (result.status !== 0) return Promise.resolve(false)
    const services = result.stdout.split('\n').map((service) => service.trim())
    return Promise.resolve(services.includes('api') && services.includes('postgres'))
  } catch {
    return Promise.resolve(false)
  }
}

/**
 * Roda um script Python DENTRO do container da API (stdin, nunca `-c`).
 * Usado para autenticar de um IP diferente do host: o bucket de login é
 * `127.0.0.1:auth.login`, separado do bucket dos specs de browser.
 */
export function execInApi(script: string, args: string[]): Promise<string> {
  const result = runCompose(['exec', '-T', 'api', 'python', '-', ...args], script)
  if (result.status !== 0) return Promise.reject(failure('exec api', result))
  return Promise.resolve(result.stdout.trim())
}

/** psql dentro do container, usando as próprias variáveis de ambiente dele. */
export function execInPostgres(sql: string): Promise<string> {
  const result = runCompose([
    'exec',
    '-T',
    'postgres',
    'sh',
    '-c',
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"',
    'sh',
    sql,
  ])
  if (result.status !== 0) return Promise.reject(failure('exec postgres', result))
  return Promise.resolve(result.stdout.trim())
}

/** Escapa um valor para literal SQL (uso restrito a dados gerados pelo teste). */
export function sqlLiteral(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}

export function composePause(service: string): Promise<void> {
  const result = runCompose(['pause', service])
  if (result.status !== 0) return Promise.reject(failure(`pause ${service}`, result))
  return Promise.resolve()
}

export function composeUnpause(service: string): Promise<void> {
  const result = runCompose(['unpause', service])
  if (result.status !== 0) return Promise.reject(failure(`unpause ${service}`, result))
  return Promise.resolve()
}

/**
 * Espera o healthcheck do Docker voltar a `healthy`.
 *
 * Um container pausado acumula probes falhadas e fica `unhealthy`: o próximo
 * `docker compose up -d` aborta com "dependency failed to start" enquanto o
 * status não voltar a verde.
 */
export async function waitForServiceHealthy(service: string, timeoutMs = 60_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const id = runCompose(['ps', '-q', service]).stdout.trim()
    if (id) {
      const inspected = spawnSync(
        'docker',
        ['inspect', '--format', '{{.State.Health.Status}}', id],
        { encoding: 'utf8', timeout: 30_000 },
      )
      if (inspected.stdout.trim() === 'healthy') return true
    }
    await sleep(500)
  }
  return false
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolvePromise) => {
    setTimeout(resolvePromise, ms)
  })
}

/**
 * `backendAvailable` faz um único probe de 2s; no `e2e-full` a API pode ainda
 * estar subindo. Este poll evita o falso verde de "skip porque não havia stack".
 */
export async function waitForBackend(
  request: APIRequestContext,
  timeoutMs = 15_000,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await backendAvailable(request)) return true
    await sleep(500)
  }
  return false
}

const LOGIN_SCRIPT = String.raw`
import json
import sys
import urllib.error
import urllib.request

email, password = sys.argv[1], sys.argv[2]
expire = len(sys.argv) > 3 and sys.argv[3] == "--expire"

payload = json.dumps({"email": email, "password": password}).encode("utf-8")
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/auth/login",
    data=payload,
    headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
    method="POST",
)
try:
    response = urllib.request.urlopen(request, timeout=15)
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"login falhou: HTTP {exc.code} {exc.read().decode('utf-8')}\n")
    sys.exit(1)

set_cookie = response.headers.get_all("Set-Cookie") or []
if not set_cookie:
    sys.stderr.write("login sem Set-Cookie\n")
    sys.exit(1)

name, _, token = set_cookie[0].split(";", 1)[0].partition("=")
if not name or not token:
    sys.stderr.write(f"cookie de sessão ilegível: {set_cookie[0]}\n")
    sys.exit(1)

if expire:
    import asyncio

    from sqlalchemy import text

    from app.core.security import hash_session_token
    from app.db.session import SessionLocal

    async def expire_session() -> None:
        async with SessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE sessions SET expires_at = now() - interval '1 hour' "
                    "WHERE token_hash = :th"
                ),
                {"th": hash_session_token(token)},
            )
            await session.commit()

    asyncio.run(expire_session())

sys.stdout.write(f"{name}\t{token}\n")
`

/**
 * Login real executado DENTRO do container da API (IP 127.0.0.1): não consome
 * o bucket de 5/60s do IP do host. Devolve o nome do cookie e o token cru.
 *
 * `expireNow` expira só a sessão recém-criada (via token_hash) e serve como
 * atalho; para expirar todas as sessões de um usuário, prefira um UPDATE
 * escopado por e-mail.
 */
export async function loginViaApiContainer(
  email: string,
  password: string,
  opts: { expireNow?: boolean } = {},
): Promise<{ cookieName: string; token: string }> {
  const args = [email, password]
  if (opts.expireNow) args.push('--expire')

  const output = await execInApi(LOGIN_SCRIPT, args)
  const line = output
    .split('\n')
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .at(-1)
  const [cookieName, token] = line?.split('\t') ?? []
  if (!cookieName || !token) {
    throw new Error(`login no container devolveu saída inesperada: ${output}`)
  }
  return { cookieName, token }
}

/** Cookie de storageState para o baseURL http://localhost:8000. */
export function sessionCookie(cookieName: string, token: string): Cookie {
  return {
    name: cookieName,
    value: token,
    domain: 'localhost',
    path: '/',
    expires: -1,
    httpOnly: true,
    secure: false,
    sameSite: 'Lax',
  }
}

/**
 * Zera os contadores de login. O bucket por conta real é `acct:login:<email>`
 * (scope "login"), não `acct:auth.login:<email>`; limpamos os dois formatos
 * para não depender do detalhe.
 */
export async function resetLoginBuckets(): Promise<void> {
  await execInPostgres(
    "DELETE FROM rate_limits WHERE key LIKE '%:auth.login' " +
      "OR key LIKE 'acct:login:%' OR key LIKE 'acct:auth.login:%'",
  )
}

/**
 * Zera o contador por IP do register (`auth.register`, 10/60s). A suíte soma
 * vários cadastros por run e o bucket é compartilhado pelo IP do host.
 */
export async function resetRegisterBuckets(): Promise<void> {
  await execInPostgres("DELETE FROM rate_limits WHERE key LIKE '%:auth.register'")
}
