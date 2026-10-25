/**
 * Converte o JSON da API (base64url) para as options que a WebAuthn API do
 * browser exige (`BufferSource` nos campos binários).
 */
import type { PasskeyAuthenticationOptionsOut, PasskeyRegistrationOptionsOut } from '../api/types'

import { base64UrlToBufferSource } from './base64'

export function toRegistrationOptions(
  json: PasskeyRegistrationOptionsOut,
): PublicKeyCredentialCreationOptions {
  return {
    rp: json.rp,
    user: { ...json.user, id: base64UrlToBufferSource(json.user.id) },
    challenge: base64UrlToBufferSource(json.challenge),
    pubKeyCredParams: json.pubKeyCredParams,
    timeout: json.timeout,
    excludeCredentials: json.excludeCredentials.map((cred) => ({
      id: base64UrlToBufferSource(cred.id),
      type: cred.type,
    })),
    authenticatorSelection: {
      residentKey: json.authenticatorSelection.residentKey as ResidentKeyRequirement,
      requireResidentKey: json.authenticatorSelection.requireResidentKey,
      userVerification: json.authenticatorSelection.userVerification as UserVerificationRequirement,
    },
    // O schema declara string livre; o DOM exige a union literal.
    attestation: json.attestation as AttestationConveyancePreference,
  }
}

export function toAuthenticationOptions(
  json: PasskeyAuthenticationOptionsOut,
): PublicKeyCredentialRequestOptions {
  return {
    challenge: base64UrlToBufferSource(json.challenge),
    timeout: json.timeout,
    rpId: json.rpId,
    allowCredentials: json.allowCredentials.map((cred) => ({
      id: base64UrlToBufferSource(cred.id),
      type: cred.type,
    })),
    // O schema declara string livre; o DOM exige a union literal.
    userVerification: json.userVerification as UserVerificationRequirement,
  }
}
