import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { ApiError } from '../api/client'
import { AuthApi } from '../api/endpoints'
import type { UserOut } from '../api/types'

interface AuthState {
  user: UserOut | null
  loading: boolean
  error: string | null
}

interface AuthContextValue extends AuthState {
  /** Atualiza o user no contexto (após login, logout, etc.). */
  setUser: (user: UserOut | null) => void
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
        setState({ user: null, loading: false, error: null })
      } else {
        setState({ user: null, loading: false, error: (err as Error).message })
      }
    }
  }, [])

  const setUser = useCallback((user: UserOut | null) => {
    setState({ user, loading: false, error: null })
  }, [])

  const logout = useCallback(async () => {
    await AuthApi.logout()
    setState({ user: null, loading: false, error: null })
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, setUser, logout }),
    [state, setUser, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth precisa estar dentro de <AuthProvider>')
  return ctx
}
