/**
 * Reexports limpos do schema OpenAPI gerado.
 * Use estes tipos no app; o resto de `schema` é detalhe de paths/operations.
 *
 * Regenerar: `just web-types`.
 */
import type { components } from './schema'

export type UserOut = components['schemas']['UserOut']
export type RegisterIn = components['schemas']['RegisterIn']
export type LoginIn = components['schemas']['LoginIn']
export type PasswordChangeIn = components['schemas']['PasswordChangeIn']
export type ForgotPasswordIn = components['schemas']['ForgotPasswordIn']
export type ResetPasswordIn = components['schemas']['ResetPasswordIn']
export type EmailOtpRequestIn = components['schemas']['EmailOtpRequestIn']
export type EmailOtpVerifyIn = components['schemas']['EmailOtpVerifyIn']
export type HealthResponse = components['schemas']['HealthResponse']
export type EnqueueEmailIn = components['schemas']['EnqueueEmailIn']
export type EnqueueEmailOut = components['schemas']['EnqueueEmailOut']
export type HTTPValidationError = components['schemas']['HTTPValidationError']
export type ValidationError = components['schemas']['ValidationError']

export type LoginOut = components['schemas']['LoginOut']
export type OkOut = components['schemas']['OkOut']
export type TotpSetupOut = components['schemas']['TotpSetupOut']
export type TotpConfirmOut = components['schemas']['TotpConfirmOut']
export type TwoFactorVerifyIn = components['schemas']['TwoFactorVerifyIn']
export type TwoFactorStatusOut = components['schemas']['TwoFactorStatusOut']
export type PasskeyItemOut = components['schemas']['PasskeyItemOut']
export type PendingIn = components['schemas']['PendingIn']

export type PasskeyRegisterOptionsOut = components['schemas']['PasskeyRegisterOptionsOut']
export type PasskeyLoginOptionsOut = components['schemas']['PasskeyLoginOptionsOut']
export type PasskeyRegistrationOptionsOut = components['schemas']['PasskeyRegistrationOptionsOut']
export type PasskeyAuthenticationOptionsOut =
  components['schemas']['PasskeyAuthenticationOptionsOut']
export type PasskeyRegisterIn = components['schemas']['PasskeyRegisterIn']
export type PasskeyLoginIn = components['schemas']['PasskeyLoginIn']
export type PasskeyRegistrationCredential = components['schemas']['PasskeyRegistrationCredential']
export type PasskeyAuthenticationCredential =
  components['schemas']['PasskeyAuthenticationCredential']

export type PolicyOut = components['schemas']['PolicyOut']
export type RuleOut = components['schemas']['RuleOut']
export type ActorOut = components['schemas']['ActorOut']
export type UserUpdateIn = components['schemas']['UserUpdateIn']
