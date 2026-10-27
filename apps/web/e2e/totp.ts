import { createHmac } from 'node:crypto'

/**
 * TOTP (RFC 6238) mínimo para o e2e — sem dependência npm.
 *
 * O servidor usa pyotp com `valid_window=1` (aceita ±30s), então o código do
 * instante atual basta; relógio local e do container ficam na mesma máquina.
 */

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
const PERIOD_S = 30
const DIGITS = 6

function base32Decode(secret: string): Buffer {
  const clean = secret.replace(/=+$/, '').replace(/\s+/g, '').toUpperCase()
  let bits = 0
  let value = 0
  const bytes: number[] = []

  for (const char of clean) {
    const index = BASE32_ALPHABET.indexOf(char)
    if (index === -1) throw new Error(`segredo base32 inválido: ${char}`)

    value = (value << 5) | index
    bits += 5
    if (bits >= 8) {
      bits -= 8
      bytes.push((value >>> bits) & 0xff)
    }
  }

  return Buffer.from(bytes)
}

/** Código TOTP de 6 dígitos para `secret` no instante `atMs`. */
export function generateTotp(secret: string, atMs: number = Date.now()): string {
  const counter = Math.floor(atMs / 1000 / PERIOD_S)
  const counterBuffer = Buffer.alloc(8)
  counterBuffer.writeUInt32BE(Math.floor(counter / 2 ** 32), 0)
  counterBuffer.writeUInt32BE(counter >>> 0, 4)

  const digest = createHmac('sha1', base32Decode(secret)).update(counterBuffer).digest()
  const offset = digest[digest.length - 1] & 0x0f
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    (digest[offset + 1] << 16) |
    (digest[offset + 2] << 8) |
    digest[offset + 3]

  return (binary % 10 ** DIGITS).toString().padStart(DIGITS, '0')
}

/** Vetor de teste da RFC 6238 (SHA-1, T=59s): 94287082 → 287082. */
export const RFC6238_VECTOR = {
  secret: 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',
  atMs: 59_000,
  code: '287082',
} as const
