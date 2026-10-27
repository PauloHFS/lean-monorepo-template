import { type APIRequestContext, expect, test } from '@playwright/test'

import {
  composeAvailable,
  composePause,
  composeUnpause,
  waitForBackend,
  waitForServiceHealthy,
} from './db'

/**
 * Readiness degradado — DEVE ser o último arquivo (ordem alfabética): pausar o
 * Postgres é mutação global da stack.
 *
 * `pause` (SIGSTOP) em vez de `stop`: o processo continua com o container
 * "running", o probe de 2s do /healthz estoura de forma determinística e
 * `unpause` retoma sem refazer o pool de conexões.
 */

let stackProbe: Promise<boolean> | undefined

function stackReady(request: APIRequestContext): Promise<boolean> {
  stackProbe ??= (async () => {
    if (!(await composeAvailable())) return false
    return waitForBackend(request)
  })()
  return stackProbe
}

test('R5 — /healthz responde 503/degraded com o Postgres pausado', async ({ request }) => {
  test.setTimeout(90_000)
  const ready = await stackReady(request)
  test.skip(!ready, 'stack real indisponível (API/Postgres fora do ar)')

  await composePause('postgres')
  try {
    // O probe interno tem teto de 2s; basta esperar o banco parar de responder.
    await expect
      .poll(async () => (await request.get('/api/v1/healthz')).status(), {
        timeout: 15_000,
        intervals: [250, 500, 1000],
      })
      .toBe(503)

    const res = await request.get('/api/v1/healthz')
    expect(res.status()).toBe(503)
    expect(await res.json()).toEqual({ status: 'degraded', db: false })
  } finally {
    // Sempre devolve a stack utilizável, mesmo se uma asserção falhar.
    await composeUnpause('postgres').catch(() => undefined)
    // Pausado, o container acumula probes falhadas e fica `unhealthy`: sem
    // esperar o healthcheck voltar a verde, o próximo `docker compose up -d`
    // aborta com "dependency failed to start".
    await waitForServiceHealthy('postgres')
  }

  // Prova a recuperação: readiness volta a 200 depois do unpause.
  await expect
    .poll(async () => (await request.get('/api/v1/healthz')).status(), {
      timeout: 30_000,
      intervals: [500, 1000, 2000],
    })
    .toBe(200)
})
