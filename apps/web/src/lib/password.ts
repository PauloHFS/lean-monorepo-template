/**
 * Validação e estimativa de força de senha segundo o NIST SP 800-63B / OWASP ASVS:
 * - Sem regras artificiais de composição (não obriga símbolos específicos).
 * - Rejeita senhas comuns vazadas, caracteres repetidos e senha igual ao e-mail.
 * - Incentiva passphrases longas (12+ caracteres) com feedback visual claro.
 */

const COMMON_WEAK_PASSWORDS = new Set([
  '12345678',
  '123456789',
  '1234567890',
  '87654321',
  'password',
  'password1',
  'password123',
  'qwerty123',
  'qwertyuiop',
  '11111111',
  '00000000',
  'iloveyou',
  'admin123',
  'welcome1',
  'letmein1',
  'monkey123',
  'dragon123',
  'sunshine1',
  'princess1',
  'football1',
  'baseball1',
  'abc12345',
  'abc123456',
  'senha123',
  'senha1234',
  'mudar123',
  'mudar@123',
  'brasil123',
])

export function validateNistPasswordClient(password: string, email?: string): string | null {
  if (password.length < 8) return 'mínimo de 8 caracteres'
  if (new TextEncoder().encode(password).length > 72) return 'máximo de 72 bytes'
  const low = password.trim().toLowerCase()
  if (COMMON_WEAK_PASSWORDS.has(low)) {
    return 'Esta senha é muito comum e insegura. Escolha uma senha mais forte.'
  }
  if (new Set(low).size <= 1) {
    return 'A senha não pode conter apenas caracteres repetidos.'
  }
  if (email) {
    const emailNorm = email.trim().toLowerCase()
    const localPart = emailNorm.split('@')[0] ?? ''
    if (low === emailNorm || (localPart.length >= 4 && low === localPart)) {
      return 'A senha não pode ser igual ao seu e-mail.'
    }
  }
  return null
}

export type PasswordStrength = {
  score: 0 | 1 | 2 | 3 | 4
  label: string
  colorClass: string
}

export function evaluatePasswordStrength(password: string, email?: string): PasswordStrength {
  if (!password) {
    return { score: 0, label: '', colorClass: 'bg-slate-200' }
  }
  const nistErr = validateNistPasswordClient(password, email)
  if (nistErr) {
    return { score: 1, label: 'Fraca (bloqueada pelo padrão NIST)', colorClass: 'bg-red-500' }
  }

  let classes = 0
  if (/[a-z]/.test(password)) classes += 1
  if (/[A-Z]/.test(password)) classes += 1
  if (/[0-9]/.test(password)) classes += 1
  if (/[^a-zA-Z0-9]/.test(password)) classes += 1

  if (password.length >= 16 || (password.length >= 12 && classes >= 3)) {
    return { score: 4, label: 'Excelente (padrão NIST recomendado)', colorClass: 'bg-emerald-600' }
  }
  if (password.length >= 12 || (password.length >= 10 && classes >= 2)) {
    return { score: 3, label: 'Forte', colorClass: 'bg-green-500' }
  }
  return {
    score: 2,
    label: 'Razoável (dica: use 12+ caracteres ou uma frase-senha)',
    colorClass: 'bg-amber-500',
  }
}
