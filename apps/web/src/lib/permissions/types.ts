/**
 * Tipos espelhados do backend (contrato OpenAPI).
 */
import type { ActorOut, PolicyOut, RuleOut } from '../../api/types'

export type Action = 'create' | 'read' | 'list' | 'update' | 'delete' | (string & {})
export type Resource = 'user' | 'email' | (string & {})
export type Role = 'admin' | 'member' | (string & {})

export type Scalar = string | number | boolean | null

export type EntityContext = Record<string, unknown>
export type EnvContext = Record<string, Scalar>

export type { ActorOut, PolicyOut, RuleOut }
