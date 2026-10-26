/**
 * Traduz erros de transporte/HTTP para mensagens em PT-BR.
 *
 * O `detail` do backend pode vir em inglês (credenciais, rate limit) ou como
 * lista de validação do FastAPI (422). Só reutilizamos o texto do servidor
 * quando ele já é útil (400/422, tratado em `client.ts`); o resto recebe uma
 * mensagem própria por status.
 */
import { ApiError } from '../api/client'

const STATUS_MESSAGES: Record<number, string> = {
  403: 'Sua conta está inativa ou sem permissão.',
  404: 'Recurso não encontrado.',
  409: 'Os dados mudaram. Recarregue a página e tente novamente.',
  429: 'Muitas tentativas. Aguarde um instante e tente novamente.',
}

const DEFAULT_UNAUTHORIZED = 'Sessão expirada. Entre novamente.'

export function humanizeError(
  err: unknown,
  unauthorizedMessage: string = DEFAULT_UNAUTHORIZED,
): string {
  if (err instanceof ApiError) {
    if (err.status === 400 || err.status === 422) return err.message
    if (err.status === 401) return unauthorizedMessage
    if (err.status >= 500) return 'O servidor falhou. Tente novamente em instantes.'
    return STATUS_MESSAGES[err.status] ?? 'Não foi possível concluir a solicitação.'
  }

  return 'Não foi possível conectar ao servidor. Verifique sua conexão.'
}
