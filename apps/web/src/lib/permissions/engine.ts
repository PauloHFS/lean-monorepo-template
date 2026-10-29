/**
 * Motor de avaliação no frontend (idêntico ao engine.py do backend).
 */
import type {
  Action,
  EntityContext,
  EnvContext,
  PolicyOut,
  Resource,
  RuleOut,
  Scalar,
} from './types'

type CondNode =
  | { kind: 'always' }
  | { kind: 'eq'; left: Operand; right: Operand }
  | { kind: 'not'; cond: CondNode }
  | { kind: 'all'; conds: CondNode[] }
  | { kind: 'any'; conds: CondNode[] }

type Operand =
  | { kind: 'ref'; scope: 'actor' | 'resource' | 'env'; attr: string }
  | { kind: 'lit'; value: Scalar }

interface EvalContext {
  actor: Record<string, Scalar>
  resource: Record<string, Scalar> | null
  env: Record<string, Scalar>
}

function resolve(op: Operand, ctx: EvalContext): Scalar {
  if (op.kind === 'lit') return op.value
  const bag = op.scope === 'actor' ? ctx.actor : op.scope === 'resource' ? ctx.resource : ctx.env
  if (!bag || !(op.attr in bag)) {
    throw new Error(`Missing attribute: ${op.scope}.${op.attr}`)
  }
  return bag[op.attr] as Scalar
}

export function evaluateCond(cond: CondNode, ctx: EvalContext): boolean {
  switch (cond.kind) {
    case 'always':
      return true
    case 'eq':
      return resolve(cond.left, ctx) === resolve(cond.right, ctx)
    case 'not':
      return !evaluateCond(cond.cond, ctx)
    case 'all':
      return cond.conds.every((c) => evaluateCond(c, ctx))
    case 'any':
      return cond.conds.some((c) => evaluateCond(c, ctx))
    default:
      return false
  }
}

function normalize(entity?: EntityContext | null): Record<string, Scalar> | null {
  if (!entity) return null
  const out: Record<string, Scalar> = {}
  for (const [k, v] of Object.entries(entity)) {
    if (v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      out[k] = v
    } else if (typeof v === 'object' && v !== null && 'id' in v) {
      out[k] = String((v as { id: unknown }).id)
    } else {
      out[k] = String(v)
    }
  }
  return out
}

export function matchingRules(
  policy: PolicyOut,
  action: Action,
  resource: Resource,
  entity?: EntityContext | null,
  env?: EnvContext,
): RuleOut[] {
  const actorAttrs: Record<string, Scalar> = {
    id: policy.actor.id,
    role: policy.actor.role,
    is_active: true,
  }
  const ctx: EvalContext = {
    actor: actorAttrs,
    resource: normalize(entity),
    env: env || {},
  }

  const matched: RuleOut[] = []
  for (const rule of policy.rules) {
    if (rule.action === action && rule.resource === resource) {
      try {
        if (evaluateCond(rule.when as CondNode, ctx)) {
          matched.push(rule)
        }
      } catch {}
    }
  }
  return matched
}

export function can(
  policy: PolicyOut | null | undefined,
  action: Action,
  resource: Resource,
  entity?: EntityContext | null,
  env?: EnvContext,
): boolean {
  if (!policy) return false
  return matchingRules(policy, action, resource, entity, env).length > 0
}

export function canClass(
  policy: PolicyOut | null | undefined,
  action: Action,
  resource: Resource,
): boolean {
  if (!policy) return false
  return policy.rules.some((r) => r.action === action && r.resource === resource)
}

export function allowedFields(
  policy: PolicyOut | null | undefined,
  action: Action,
  resource: Resource,
  entity?: EntityContext | null,
  env?: EnvContext,
): Set<string> | null {
  if (!policy) return new Set()
  const rules = matchingRules(policy, action, resource, entity, env)
  if (rules.length === 0) return new Set()

  const union = new Set<string>()
  for (const rule of rules) {
    if (!rule.fields) return null // Todas liberadas
    for (const f of rule.fields) union.add(f)
  }
  return union
}
