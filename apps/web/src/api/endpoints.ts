/**
 * Helpers tipados por endpoint. Usa os types do schema OpenAPI gerado.
 * Para regenerar: `just web-types`.
 */
import type { EnqueueEmailIn, EnqueueEmailOut, HealthResponse, LoginIn, UserOut } from './types'

import { api } from './client'

type PasskeyOptionsOut = { options: Record<string, unknown>; challenge: string }
type PasskeyCredentialIn = { challenge: string; credential: Record<string, unknown> }

export const AuthApi = {
  me: () => api.get<UserOut>('/api/v1/auth/me'),
  login: (body: LoginIn) =>
    api.post<UserOut | { requires_2fa: boolean }>('/api/v1/auth/login', body),
  logout: () => api.post<void>('/api/v1/auth/logout'),
}

export const HealthApi = {
  check: () => api.get<HealthResponse>('/api/v1/healthz'),
}

export const UsersApi = {
  me: () => api.get<UserOut>('/api/v1/users/me'),
  enqueueEmail: (body: EnqueueEmailIn) =>
    api.post<EnqueueEmailOut>('/api/v1/users/enqueue-email', body),
}

// Helpers sem tipo gerado (OpenAPI devolve dict livre nesses casos).
export const TwoFactorApi = {
  // TOTP setup (logado)
  totpSetup: () => api.post<{ secret: string; otpauth_uri: string }>('/api/v1/auth/2fa/totp/setup'),

  totpConfirm: (code: string) =>
    api.post<{ enabled: boolean; recovery_codes: string[] }>('/api/v1/auth/2fa/totp/confirm', {
      code,
    }),

  // TOTP verify (no fluxo de login, sem cookie ainda)
  totpVerify: (pending_token: string, code: string) =>
    api.post<{ ok: boolean }>('/api/v1/auth/2fa/verify', {
      pending_token,
      code,
    }),

  // Passkey
  passkeyRegisterOptions: () =>
    api.post<PasskeyOptionsOut>('/api/v1/auth/2fa/passkey/register/options'),

  passkeyRegisterVerify: (payload: PasskeyCredentialIn) =>
    api.post<void>('/api/v1/auth/2fa/passkey/register/verify', payload),

  passkeyLoginOptions: (body: { pending_token: string }) =>
    api.post<PasskeyOptionsOut>('/api/v1/auth/2fa/passkey/login/options', body),

  passkeyLoginVerify: (payload: PasskeyCredentialIn) =>
    api.post<{ ok: boolean }>('/api/v1/auth/2fa/passkey/login/verify', payload),
}
