/**
 * Helpers tipados por endpoint. Usa os types do schema OpenAPI gerado.
 * Para regenerar: `just web-types`.
 */

import { api } from './client'
import type {
  EmailOtpRequestIn,
  EmailOtpVerifyIn,
  EnqueueEmailIn,
  EnqueueEmailOut,
  ForgotPasswordIn,
  HealthResponse,
  LoginIn,
  LoginOut,
  OkOut,
  PasskeyLoginIn,
  PasskeyLoginOptionsOut,
  PasskeyRegisterIn,
  PasskeyRegisterOptionsOut,
  PasswordChangeIn,
  PendingIn,
  PolicyOut,
  RegisterIn,
  ResetPasswordIn,
  TotpConfirmOut,
  TotpSetupOut,
  TwoFactorStatusOut,
  TwoFactorVerifyIn,
  UserOut,
  UserUpdateIn,
} from './types'

export const AuthApi = {
  me: () => api.get<UserOut>('/api/v1/auth/me'),
  register: (body: RegisterIn) => api.post<UserOut>('/api/v1/auth/register', body),
  login: (body: LoginIn) => api.post<LoginOut>('/api/v1/auth/login', body),
  logout: () => api.post<void>('/api/v1/auth/logout'),
  changePassword: (body: PasswordChangeIn) => api.post<OkOut>('/api/v1/auth/password/change', body),
  forgotPassword: (body: ForgotPasswordIn) => api.post<OkOut>('/api/v1/auth/password/forgot', body),
  resetPassword: (body: ResetPasswordIn) => api.post<OkOut>('/api/v1/auth/password/reset', body),
  requestEmailOtp: (body: EmailOtpRequestIn) =>
    api.post<OkOut>('/api/v1/auth/otp/email/request', body),
  verifyEmailOtp: (body: EmailOtpVerifyIn) =>
    api.post<LoginOut>('/api/v1/auth/otp/email/verify', body),
}

export const HealthApi = {
  check: () => api.get<HealthResponse>('/api/v1/healthz'),
}

export const UsersApi = {
  me: () => api.get<UserOut>('/api/v1/users/me'),
  list: (limit = 50, offset = 0) =>
    api.get<UserOut[]>(`/api/v1/users?limit=${limit}&offset=${offset}`),
  update: (userId: string, body: UserUpdateIn) =>
    api.patch<UserOut>(`/api/v1/users/${userId}`, body),
  delete: (userId: string) => api.delete<void>(`/api/v1/users/${userId}`),
  enqueueEmail: (body: EnqueueEmailIn) =>
    api.post<EnqueueEmailOut>('/api/v1/users/enqueue-email', body),
}

export const TwoFactorApi = {
  status: () => api.get<TwoFactorStatusOut>('/api/v1/auth/2fa/status'),

  // TOTP setup (logado)
  totpSetup: () => api.post<TotpSetupOut>('/api/v1/auth/2fa/totp/setup'),

  totpConfirm: (code: string) =>
    api.post<TotpConfirmOut>('/api/v1/auth/2fa/totp/confirm', { code }),

  totpDisable: () => api.post<OkOut>('/api/v1/auth/2fa/totp/disable'),

  totpRegenerateRecoveryCodes: () =>
    api.post<TotpConfirmOut>('/api/v1/auth/2fa/totp/recovery-codes/regenerate'),

  // TOTP verify (no fluxo de login, sem cookie ainda)
  totpVerify: (pending_token: string, code: string) =>
    api.post<OkOut>('/api/v1/auth/2fa/verify', { pending_token, code } satisfies TwoFactorVerifyIn),

  // Passkey
  passkeyRegisterOptions: () =>
    api.post<PasskeyRegisterOptionsOut>('/api/v1/auth/2fa/passkey/register/options'),

  passkeyRegisterVerify: (payload: PasskeyRegisterIn) =>
    api.post<void>('/api/v1/auth/2fa/passkey/register/verify', payload),

  passkeyDelete: (passkeyId: string) => api.delete<void>(`/api/v1/auth/2fa/passkey/${passkeyId}`),

  passkeyLoginOptions: (body: PendingIn) =>
    api.post<PasskeyLoginOptionsOut>('/api/v1/auth/2fa/passkey/login/options', body),

  passkeyLoginVerify: (payload: PasskeyLoginIn) =>
    api.post<OkOut>('/api/v1/auth/2fa/passkey/login/verify', payload),

  passkeyPasswordlessOptions: () =>
    api.post<PasskeyLoginOptionsOut>('/api/v1/auth/2fa/passkey/passwordless/options'),

  passkeyPasswordlessVerify: (payload: PasskeyLoginIn) =>
    api.post<OkOut>('/api/v1/auth/2fa/passkey/passwordless/verify', payload),
}

export const PermissionsApi = {
  myPolicy: () => api.get<PolicyOut>('/api/v1/permissions/me'),
}
