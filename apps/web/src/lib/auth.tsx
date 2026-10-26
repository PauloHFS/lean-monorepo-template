import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { ApiError } from '../api/client'
import { AuthApi } from '../api/endpoints'
import type { UserOut } from '../api/types'
import { humanizeError } from './errors'

interface AuthState {
  user: UserOut | null
  loading: boolean
  error: string | null
}

interface AuthContextValue extends AuthState {
  /** Atualiza o user no contexto (após login, logout, etc.). */
  setUser: (user: UserOut | null) => void
  /** Reconsulta /auth/me. Usado pelo retry do guard de rota. */
  refresh: () => Promise<void>
  /** Faz logout (limpa cookie no backend + estado local). */
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true, error: null })

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const user = await AuthApi.me()
      setState({ user, loading: false, error: null })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // Sem sessão é um estado válido, não um erro.
        setState({ user: null, loading: false, error: null })
      } else {
        // Falha de transporte/5xx não é logout: mantém o erro para o guard exibir.
        setState({ user: null, loading: false, error: humanizeError(err) })
      }
    }
  }, [])

  const setUser = useCallback((user: UserOut | null) => {
    setState({ user, loading: false, error: null })
  }, [])

  const logout = useCallback(async () => {
    // A sessão local é encerrada mesmo se o backend não responder.
    await AuthApi.logout().catch(() => undefined)
    setState({ user: null, loading: false, error: null })
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, setUser, refresh, logout }),
    [state, setUser, refresh, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth precisa estar dentro de <AuthProvider>')
  return ctx
}
