/**
 * React Context e Hooks para ABAC no frontend.
 * Consome a policy do endpoint /api/v1/permissions/me.
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { PermissionsApi } from '../../api/endpoints'
import { useAuth } from '../auth'
import {
  allowedFields as engineAllowedFields,
  can as engineCan,
  canClass as engineCanClass,
} from './engine'
import type { Action, EntityContext, EnvContext, PolicyOut, Resource } from './types'

interface PermissionsContextValue {
  policy: PolicyOut | null
  loading: boolean
  can: (
    action: Action,
    resource: Resource,
    entity?: EntityContext | null,
    env?: EnvContext,
  ) => boolean
  canClass: (action: Action, resource: Resource) => boolean
  allowedFields: (
    action: Action,
    resource: Resource,
    entity?: EntityContext | null,
    env?: EnvContext,
  ) => Set<string> | null
  refresh: () => Promise<void>
}

const PermissionsContext = createContext<PermissionsContextValue | null>(null)

export function PermissionsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [policy, setPolicy] = useState<PolicyOut | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    if (!user) {
      setPolicy(null)
      return
    }
    setLoading(true)
    try {
      const p = await PermissionsApi.myPolicy()
      setPolicy(p)
    } catch {
      setPolicy(null)
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value = useMemo<PermissionsContextValue>(() => {
    return {
      policy,
      loading,
      can: (action, resource, entity, env) => engineCan(policy, action, resource, entity, env),
      canClass: (action, resource) => engineCanClass(policy, action, resource),
      allowedFields: (action, resource, entity, env) =>
        engineAllowedFields(policy, action, resource, entity, env),
      refresh,
    }
  }, [policy, loading, refresh])

  return <PermissionsContext.Provider value={value}>{children}</PermissionsContext.Provider>
}

export function usePermissions(): PermissionsContextValue {
  const ctx = useContext(PermissionsContext)
  if (!ctx) {
    throw new Error('usePermissions precisa ser usado dentro de um <PermissionsProvider>')
  }
  return ctx
}

/**
 * Componente declarativo <Can action="..." resource="...">
 */
export function Can({
  action,
  resource,
  entity,
  env,
  fallback = null,
  children,
}: {
  action: Action
  resource: Resource
  entity?: EntityContext | null
  env?: EnvContext
  fallback?: ReactNode
  children: ReactNode
}) {
  const { can } = usePermissions()
  if (!can(action, resource, entity, env)) {
    return <>{fallback}</>
  }
  return <>{children}</>
}
