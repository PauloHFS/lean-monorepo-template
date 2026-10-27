import { composeAvailable, resetLoginBuckets, resetRegisterBuckets } from './db'

/**
 * Limpa os buckets de rate limit de login e de register antes da suíte.
 *
 * O bucket é 5/60s (login) e 10/60s (register) e persiste no Postgres entre
 * execuções; sem isso dois `just e2e-full` seguidos dentro da mesma janela
 * herdariam contadores e levariam 429.
 * Sem stack no ar (o CI roda só os specs mockados) é no-op, nunca falha.
 */
export default async function globalSetup(): Promise<void> {
  if (!(await composeAvailable())) return

  try {
    await resetLoginBuckets()
    await resetRegisterBuckets()
  } catch {
    // Stack subindo/instável não deve derrubar a suíte mockada.
    return
  }
}
