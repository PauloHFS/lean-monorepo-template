import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'

import { AuthApi, TwoFactorApi } from '../api/endpoints'
import type { PasskeyAuthenticationCredential } from '../api/types'
import { useAuth } from '../lib/auth'
import { bytesToBase64Url } from '../lib/base64'
import { humanizeError } from '../lib/errors'
import { toAuthenticationOptions } from '../lib/webauthn'

/**
 * Sem `min` de senha aqui: a política mora no backend
 * (`settings.password_min_length`) e varia por deploy. Só exigimos preenchimento.
 */
const credSchema = z.object({
  email: z.string().email('e-mail inválido'),
  password: z.string().min(1, 'informe sua senha'),
})
type CredData = z.infer<typeof credSchema>

/** TOTP (6 dígitos) ou código de recuperação (10 caracteres alfanuméricos). */
const codeSchema = z.object({
  code: z.string().trim().min(6, 'informe o código'),
})
type CodeData = z.infer<typeof codeSchema>

type Pending2fa = {
  token: string
  methods: string[]
}

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = destinationOf(location.state)
  const { user, setUser } = useAuth()
  const [step, setStep] = useState<'credentials' | 'email-otp' | 'verify'>('credentials')
  const [pending, setPending] = useState<Pending2fa | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [passkeyBusy, setPasskeyBusy] = useState(false)

  // Email OTP state
  const [otpEmail, setOtpEmail] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [otpBusy, setOtpBusy] = useState(false)

  const credForm = useForm<CredData>({
    resolver: zodResolver(credSchema),
    defaultValues: { email: '', password: '' },
  })
  const codeForm = useForm<CodeData>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: '' },
  })

  async function onSubmitCreds(values: CredData) {
    setSubmitError(null)
    try {
      const response = await AuthApi.login(values)
      if (response.requires_2fa) {
        setPending({ token: response.pending_token ?? '', methods: response.methods })
        setStep('verify')
        return
      }
      if (!response.user) {
        setSubmitError('Sessão inválida. Tente novamente.')
        return
      }
      setUser(response.user)
      navigate(from, { replace: true })
    } catch (err) {
      setSubmitError(humanizeError(err, 'E-mail ou senha incorretos.'))
    }
  }

  async function onSendEmailOtp() {
    if (otpBusy || passkeyBusy) return
    setSubmitError(null)
    const emailVal = credForm.getValues('email').trim()
    const parsed = z.string().email().safeParse(emailVal)
    if (!parsed.success) {
      credForm.setError('email', { message: 'informe seu e-mail para receber o código' })
      return
    }
    credForm.clearErrors('email')
    setOtpBusy(true)
    try {
      await AuthApi.requestEmailOtp({ email: parsed.data })
      setOtpEmail(parsed.data)
      setOtpCode('')
      setStep('email-otp')
    } catch (err) {
      setSubmitError(humanizeError(err, 'Não foi possível enviar o código por e-mail.'))
    } finally {
      setOtpBusy(false)
    }
  }

  async function onVerifyEmailOtp(e: React.FormEvent) {
    e.preventDefault()
    if (otpBusy || otpCode.trim().length !== 6) return
    setSubmitError(null)
    setOtpBusy(true)
    try {
      const response = await AuthApi.verifyEmailOtp({
        email: otpEmail,
        code: otpCode.trim(),
      })
      if (response.requires_2fa) {
        setPending({ token: response.pending_token ?? '', methods: response.methods })
        setStep('verify')
        return
      }
      if (!response.user) {
        setSubmitError('Sessão inválida. Tente novamente.')
        return
      }
      setUser(response.user)
      navigate(from, { replace: true })
    } catch (err) {
      setSubmitError(humanizeError(err, 'Código inválido ou expirado.'))
      setOtpCode('')
    } finally {
      setOtpBusy(false)
    }
  }

  async function onSubmitCode(values: CodeData) {
    if (!pending) return
    setSubmitError(null)
    try {
      await TwoFactorApi.totpVerify(pending.token, values.code)
      const me = await AuthApi.me()
      setUser(me)
      navigate(from, { replace: true })
    } catch (err) {
      setSubmitError(humanizeError(err, 'Código inválido ou expirado.'))
      codeForm.reset({ code: '' })
    }
  }

  async function onUsePasskey() {
    if (!pending || passkeyBusy) return
    setSubmitError(null)
    setPasskeyBusy(true)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyLoginOptions({
        pending_token: pending.token,
      })

      const credential = await navigator.credentials.get({
        publicKey: toAuthenticationOptions(options),
      })

      if (!(credential instanceof PublicKeyCredential)) {
        setSubmitError('Autenticação cancelada.')
        return
      }

      const resp = credential.response
      if (!(resp instanceof AuthenticatorAssertionResponse)) {
        setSubmitError('Resposta inesperada do autenticador.')
        return
      }

      const credentialPayload: PasskeyAuthenticationCredential = {
        id: credential.id,
        rawId: bytesToBase64Url(credential.rawId),
        type: 'public-key',
        response: {
          clientDataJSON: bytesToBase64Url(resp.clientDataJSON),
          authenticatorData: bytesToBase64Url(resp.authenticatorData),
          signature: bytesToBase64Url(resp.signature),
          userHandle: resp.userHandle ? bytesToBase64Url(resp.userHandle) : undefined,
        },
      }
      await TwoFactorApi.passkeyLoginVerify({ challenge, credential: credentialPayload })

      const me = await AuthApi.me()
      setUser(me)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setSubmitError('Autenticação cancelada pelo usuário.')
      } else {
        setSubmitError(humanizeError(err, 'Não foi possível autenticar com a passkey.'))
      }
    } finally {
      setPasskeyBusy(false)
    }
  }

  async function onPasswordlessPasskey() {
    if (passkeyBusy) return
    setSubmitError(null)
    setPasskeyBusy(true)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyPasswordlessOptions()

      const credential = await navigator.credentials.get({
        publicKey: toAuthenticationOptions(options),
      })

      if (!(credential instanceof PublicKeyCredential)) {
        setSubmitError('Autenticação cancelada.')
        return
      }

      const resp = credential.response
      if (!(resp instanceof AuthenticatorAssertionResponse)) {
        setSubmitError('Resposta inesperada do autenticador.')
        return
      }

      const credentialPayload: PasskeyAuthenticationCredential = {
        id: credential.id,
        rawId: bytesToBase64Url(credential.rawId),
        type: 'public-key',
        response: {
          clientDataJSON: bytesToBase64Url(resp.clientDataJSON),
          authenticatorData: bytesToBase64Url(resp.authenticatorData),
          signature: bytesToBase64Url(resp.signature),
          userHandle: resp.userHandle ? bytesToBase64Url(resp.userHandle) : undefined,
        },
      }
      await TwoFactorApi.passkeyPasswordlessVerify({ challenge, credential: credentialPayload })

      const me = await AuthApi.me()
      setUser(me)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setSubmitError('Autenticação cancelada pelo usuário.')
      } else {
        setSubmitError(humanizeError(err, 'Não foi possível entrar com a passkey.'))
      }
    } finally {
      setPasskeyBusy(false)
    }
  }

  function onCancel2fa() {
    setPending(null)
    setStep('credentials')
    setSubmitError(null)
    codeForm.reset({ code: '' })
  }

  // Já autenticado: não faz sentido mostrar o formulário de login.
  if (user) return <Navigate to={from} replace />

  if (step === 'email-otp') {
    return (
      <main className="grid min-h-full place-items-center p-4 sm:p-6">
        <form onSubmit={onVerifyEmailOtp} className="card w-full max-w-sm space-y-4">
          <header className="space-y-1">
            <h1 className="text-xl font-semibold">Código enviado por e-mail</h1>
            <p className="text-sm text-slate-500">
              Enviamos um código de 6 dígitos para{' '}
              <span className="font-medium text-slate-800">{otpEmail}</span>.
            </p>
          </header>

          <div className="space-y-1">
            <label htmlFor="email-otp-code" className="block text-sm text-slate-700">
              Código de 6 dígitos
            </label>
            <input
              id="email-otp-code"
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              autoComplete="one-time-code"
              placeholder="000000"
              required
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
              className="input text-center font-mono text-lg tracking-widest"
            />
            <p className="text-xs text-slate-500">Válido por 10 minutos para um único acesso.</p>
          </div>

          {submitError && (
            <p role="alert" className="text-sm text-red-600">
              {submitError}
            </p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => {
                setStep('credentials')
                setSubmitError(null)
              }}
              className="btn-ghost flex-1"
            >
              Voltar
            </button>
            <button
              type="submit"
              disabled={otpBusy || otpCode.length !== 6}
              className="btn-primary flex-1"
            >
              {otpBusy ? 'Verificando…' : 'Confirmar código'}
            </button>
          </div>
        </form>
      </main>
    )
  }

  if (step === 'verify' && pending) {
    const showPasskey = pending.methods.includes('passkey')
    const codeError = codeForm.formState.errors.code

    return (
      <main className="grid min-h-full place-items-center p-4 sm:p-6">
        <form
          onSubmit={codeForm.handleSubmit(onSubmitCode)}
          className="card w-full max-w-sm space-y-4"
        >
          <header className="space-y-1">
            <h1 className="text-xl font-semibold">Verificação em duas etapas</h1>
            <p className="text-sm text-slate-500">Confirme o acesso com seu segundo fator.</p>
          </header>

          <div className="space-y-1">
            <label htmlFor="login-code" className="block text-sm text-slate-700">
              Código
            </label>
            <input
              id="login-code"
              type="text"
              autoComplete="one-time-code"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={Boolean(codeError)}
              aria-describedby={codeError ? 'login-code-hint login-code-error' : 'login-code-hint'}
              {...codeForm.register('code')}
              className="input"
            />
            <p id="login-code-hint" className="text-xs text-slate-500">
              Use o código de 6 dígitos do app autenticador ou um código de recuperação.
            </p>
            {codeError && (
              <span id="login-code-error" role="alert" className="block text-xs text-red-600">
                {codeError.message}
              </span>
            )}
          </div>

          {submitError && (
            <p role="alert" className="text-sm text-red-600">
              {submitError}
            </p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button type="button" onClick={onCancel2fa} className="btn-ghost flex-1">
              Cancelar
            </button>
            <button
              type="submit"
              disabled={codeForm.formState.isSubmitting || passkeyBusy}
              className="btn-primary flex-1"
            >
              {codeForm.formState.isSubmitting ? 'Verificando…' : 'Verificar'}
            </button>
          </div>

          {showPasskey && (
            <button
              type="button"
              onClick={() => void onUsePasskey()}
              disabled={passkeyBusy || codeForm.formState.isSubmitting}
              className="btn-ghost w-full"
            >
              {passkeyBusy ? 'Aguardando autenticador…' : 'Usar passkey'}
            </button>
          )}
        </form>
      </main>
    )
  }

  const emailError = credForm.formState.errors.email
  const passwordError = credForm.formState.errors.password

  return (
    <main className="grid min-h-full place-items-center p-4 sm:p-6">
      <form
        onSubmit={credForm.handleSubmit(onSubmitCreds)}
        className="card w-full max-w-sm space-y-4"
      >
        <header className="space-y-1">
          <h1 className="text-xl font-semibold">Entrar</h1>
          <p className="text-sm text-slate-500">
            Use Passkey, código único por e-mail ou sua senha.
          </p>
        </header>

        <button
          type="button"
          onClick={() => void onPasswordlessPasskey()}
          disabled={passkeyBusy || credForm.formState.isSubmitting || otpBusy}
          className="btn-primary w-full"
        >
          {passkeyBusy ? 'Aguardando autenticador…' : 'Entrar com passkey'}
        </button>

        <div className="relative flex items-center py-1">
          <div className="flex-grow border-t border-slate-200" />
          <span className="mx-3 flex-shrink text-xs text-slate-400">ou com e-mail</span>
          <div className="flex-grow border-t border-slate-200" />
        </div>

        <div className="space-y-1">
          <label htmlFor="login-email" className="block text-sm text-slate-700">
            E-mail
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            aria-invalid={Boolean(emailError)}
            aria-describedby={emailError ? 'login-email-error' : undefined}
            {...credForm.register('email')}
            className="input"
          />
          {emailError && (
            <span id="login-email-error" role="alert" className="block text-xs text-red-600">
              {emailError.message}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={() => void onSendEmailOtp()}
          disabled={otpBusy || passkeyBusy || credForm.formState.isSubmitting}
          className="btn-ghost w-full"
        >
          {otpBusy ? 'Enviando código…' : 'Receber código de 6 dígitos por e-mail'}
        </button>

        <div className="space-y-1 pt-1">
          <div className="flex items-center justify-between">
            <label htmlFor="login-password" className="block text-sm text-slate-700">
              Senha
            </label>
            <Link to="/forgot-password" className="text-xs text-brand-600 hover:underline">
              Esqueceu a senha?
            </Link>
          </div>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            aria-invalid={Boolean(passwordError)}
            aria-describedby={passwordError ? 'login-password-error' : undefined}
            {...credForm.register('password')}
            className="input"
          />
          {passwordError && (
            <span id="login-password-error" role="alert" className="block text-xs text-red-600">
              {passwordError.message}
            </span>
          )}
        </div>

        {submitError && (
          <p role="alert" className="text-sm text-red-600">
            {submitError}
          </p>
        )}

        <button
          type="submit"
          disabled={credForm.formState.isSubmitting || passkeyBusy || otpBusy}
          className="btn-ghost w-full"
        >
          {credForm.formState.isSubmitting ? 'Entrando…' : 'Entrar'}
        </button>

        <p className="text-center text-sm text-slate-600">
          Não tem uma conta?{' '}
          <Link to="/register" className="font-medium text-brand-600 hover:underline">
            Criar conta
          </Link>
        </p>
      </form>
    </main>
  )
}

/** Destino guardado pelo RequireAuth; só aceita caminho interno. */
function destinationOf(state: unknown): string {
  if (state && typeof state === 'object' && 'from' in state) {
    const from = (state as { from: unknown }).from
    if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('/login')) return from
  }
  return '/dashboard'
}
