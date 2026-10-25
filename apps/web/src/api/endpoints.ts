/**
 * Helpers tipados por endpoint. Usa os types do schema OpenAPI gerado.
 * Para regenerar: `just web-types`.
 */
import type {
  EnqueueEmailIn,
  EnqueueEmailOut,
  HealthResponse,
  LoginIn,
  LoginOut,
  OkOut,
  PasskeyLoginIn,
  PasskeyLoginOptionsOut,
  PasskeyRegisterIn,
  PasskeyRegisterOptionsOut,
  PendingIn,
  TotpConfirmOut,
  TotpSetupOut,
  TwoFactorVerifyIn,
  UserOut,
} from './types'

import { api } from './client'

export const AuthApi = {
  me: () => api.get<UserOut>('/api/v1/auth/me'),
  login: (body: LoginIn) => api.post<LoginOut>('/api/v1/auth/login', body),
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

export const TwoFactorApi = {
  // TOTP setup (logado)
  totpSetup: () => api.post<TotpSetupOut>('/api/v1/auth/2fa/totp/setup'),

  totpConfirm: (code: string) =>
    api.post<TotpConfirmOut>('/api/v1/auth/2fa/totp/confirm', { code }),

  // TOTP verify (no fluxo de login, sem cookie ainda)
  totpVerify: (pending_token: string, code: string) =>
    api.post<OkOut>('/api/v1/auth/2fa/verify', { pending_token, code } satisfies TwoFactorVerifyIn),

  // Passkey
  passkeyRegisterOptions: () =>
    api.post<PasskeyRegisterOptionsOut>('/api/v1/auth/2fa/passkey/register/options'),

  passkeyRegisterVerify: (payload: PasskeyRegisterIn) =>
    api.post<void>('/api/v1/auth/2fa/passkey/register/verify', payload),

  passkeyLoginOptions: (body: PendingIn) =>
    api.post<PasskeyLoginOptionsOut>('/api/v1/auth/2fa/passkey/login/options', body),

  passkeyLoginVerify: (payload: PasskeyLoginIn) =>
    api.post<OkOut>('/api/v1/auth/2fa/passkey/login/verify', payload),
}
