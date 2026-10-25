/** Base64url SEM padding — formato exigido pelo WebAuthn (btoa puro gera +/=). */
export function bytesToBase64Url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Inverso: base64url (com ou sem padding) → bytes crus. */
export function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

/** `BufferSource` aceita `Uint8Array`; helper nomeado para o call site do WebAuthn. */
export function base64UrlToBufferSource(value: string): Uint8Array<ArrayBuffer> {
  return base64UrlToBytes(value)
}
