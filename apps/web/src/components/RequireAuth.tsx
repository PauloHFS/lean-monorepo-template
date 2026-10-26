import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from '../lib/auth'

/**
 * Guard único das rotas autenticadas.
 *
 * - enquanto a sessão resolve, mostra um estado de carregamento (sem piscar
 *   conteúdo protegido);
 * - 401 vira redirect para /login, preservando o destino em `state.from`;
 * - falha de transporte/5xx NÃO vira logout: mostra o erro com retry.
 */
export function RequireAuth() {
  const { user, loading, error, refresh } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <main className="grid min-h-full place-items-center p-4 text-slate-600 sm:p-6">
        <p role="status">Verificando sessão…</p>
      </main>
    )
  }

  if (error) {
    return (
      <main className="grid min-h-full place-items-center p-4 sm:p-6">
        <div className="card w-full max-w-md space-y-4">
          <h1 className="text-xl font-semibold">Não foi possível verificar sua sessão</h1>
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
          <button type="button" className="btn-primary w-full" onClick={() => void refresh()}>
            Tentar novamente
          </button>
        </div>
      </main>
    )
  }

  if (!user) {
    return (
      <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
    )
  }

  return <Outlet />
}
