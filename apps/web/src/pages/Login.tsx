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

const LAST_METHOD_KEY = 'lm_last_login_method'

function readLastMethod(): string | null {
  try {
    return window.localStorage.getItem(LAST_METHOD_KEY)
  } catch {
    return null
  }
}

function saveLastMethod(method: 'passkey' | 'code' | 'password'): void {
  try {
    window.localStorage.setItem(LAST_METHOD_KEY, method)
  } catch {
    // storage indisponível (modo privado): o badge é só conveniência
  }
}

/**
 * Sem `min` de senha aqui: a política mora no backend
 * (`settings.password_min_length`) e varia por deploy. A senha só é exigida
 * no modo "senha"; no modo "código" só o e-mail é validado.
 */
const credSchema = z.object({
  email: z.string().email('e-mail inválido'),
  password: z.string(),
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

type Mode = 'password' | 'code'

function KeyIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="8" cy="15" r="4" />
      <path d="m10.8 12.2 8.2-8.2m-3 3 3 3m-6-0 2 2" />
    </svg>
  )
}

function LastUsedBadge() {
  return (
    <span className="absolute -top-2 right-2 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] font-normal text-slate-500">
      Último usado
    </span>
  )
}

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = destinationOf(location.state)
  const { user, setUser } = useAuth()
  const [step, setStep] = useState<'credentials' | 'email-otp' | 'verify'>('credentials')
  const [mode, setMode] = useState<Mode>('code')
  const [pending, setPending] = useState<Pending2fa | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [passkeyBusy, setPasskeyBusy] = useState(false)
  const [lastMethod] = useState<string | null>(() => readLastMethod())

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

  function finishLogin(response: {
    requires_2fa?: boolean
    pending_token?: string | null
    methods?: string[]
    user?: Parameters<typeof setUser>[0] | null
  }): void {
    if (response.requires_2fa) {
      setPending({ token: response.pending_token ?? '', methods: response.methods ?? [] })
      setStep('verify')
      return
    }
    if (!response.user) {
      setSubmitError('Sessão inválida. Tente novamente.')
      return
    }
    setUser(response.user)
    navigate(from, { replace: true })
  }

  async function onSubmitCreds(values: CredData) {
    setSubmitError(null)
    if (mode === 'code') {
      await onSendEmailOtp(values.email)
      return
    }
    if (!values.password) {
      credForm.setError('password', { message: 'informe sua senha' })
      return
    }
    try {
      const response = await AuthApi.login({ email: values.email, password: values.password })
      if (!response.requires_2fa) saveLastMethod('password')
      finishLogin(response)
    } catch (err) {
      setSubmitError(humanizeError(err, 'E-mail ou senha incorretos.'))
    }
  }

  async function onSendEmailOtp(email: string) {
    if (otpBusy) return
    setOtpBusy(true)
    try {
      await AuthApi.requestEmailOtp({ email })
      setOtpEmail(email)
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
      const response = await AuthApi.verifyEmailOtp({ email: otpEmail, code: otpCode.trim() })
      if (!response.requires_2fa) saveLastMethod('code')
      finishLogin(response)
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

  async function runPasskeyCeremony(
    getOptions: () => Promise<{
      options: Parameters<typeof toAuthenticationOptions>[0]
      challenge: string
    }>,
    verify: (payload: {
      challenge: string
      credential: PasskeyAuthenticationCredential
    }) => Promise<unknown>,
    fallbackError: string,
  ) {
    if (passkeyBusy) return
    setSubmitError(null)
    setPasskeyBusy(true)
    try {
      const { options, challenge } = await getOptions()
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
      const payload: PasskeyAuthenticationCredential = {
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
      await verify({ challenge, credential: payload })
      saveLastMethod('passkey')
      const me = await AuthApi.me()
      setUser(me)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setSubmitError('Autenticação cancelada pelo usuário.')
      } else {
        setSubmitError(humanizeError(err, fallbackError))
      }
    } finally {
      setPasskeyBusy(false)
    }
  }

  const onUsePasskey = () =>
    pending
      ? runPasskeyCeremony(
          () => TwoFactorApi.passkeyLoginOptions({ pending_token: pending.token }),
          TwoFactorApi.passkeyLoginVerify,
          'Não foi possível autenticar com a passkey.',
        )
      : Promise.resolve()

  const onPasswordlessPasskey = () =>
    runPasskeyCeremony(
      TwoFactorApi.passkeyPasswordlessOptions,
      TwoFactorApi.passkeyPasswordlessVerify,
      'Não foi possível entrar com a passkey.',
    )

  function onCancel2fa() {
    setPending(null)
    setStep('credentials')
    setSubmitError(null)
    codeForm.reset({ code: '' })
  }

  function toggleMode() {
    setSubmitError(null)
    credForm.clearErrors()
    setMode((m) => (m === 'password' ? 'code' : 'password'))
  }

  // Já autenticado: não faz sentido mostrar o formulário de login.
  if (user) return <Navigate to={from} replace />

  if (step === 'email-otp') {
    return (
      <main className="grid min-h-full place-items-center p-4 sm:p-6">
        <form onSubmit={onVerifyEmailOtp} className="auth-card">
          <div className="auth-card-body">
            <header className="space-y-1 text-center">
              <h1 className="text-xl font-semibold text-slate-900">Verifique seu e-mail</h1>
              <p className="text-sm text-slate-500">
                Enviamos um código de 6 dígitos para{' '}
                <span className="font-medium text-slate-800">{otpEmail}</span>.
              </p>
            </header>

            <div className="space-y-1.5">
              <label htmlFor="email-otp-code" className="block text-sm font-medium text-slate-800">
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
                className="input text-center font-mono text-lg tracking-[0.5em]"
              />
              <p className="text-xs text-slate-500">Válido por 10 minutos, uso único.</p>
            </div>

            {submitError && (
              <p role="alert" className="text-sm text-red-600">
                {submitError}
              </p>
            )}

            <button
              type="submit"
              disabled={otpBusy || otpCode.length !== 6}
              className="btn-primary w-full"
            >
              {otpBusy ? 'Verificando…' : 'Continuar ▸'}
            </button>
          </div>
          <div className="auth-card-footer">
            <button
              type="button"
              onClick={() => {
                setStep('credentials')
                setSubmitError(null)
              }}
              className="font-medium text-slate-700 hover:underline"
            >
              ← Voltar
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
        <form onSubmit={codeForm.handleSubmit(onSubmitCode)} className="auth-card">
          <div className="auth-card-body">
            <header className="space-y-1 text-center">
              <h1 className="text-xl font-semibold text-slate-900">Verificação em duas etapas</h1>
              <p className="text-sm text-slate-500">Confirme o acesso com seu segundo fator.</p>
            </header>

            <div className="space-y-1.5">
              <label htmlFor="login-code" className="block text-sm font-medium text-slate-800">
                Código
              </label>
              <input
                id="login-code"
                type="text"
                autoComplete="one-time-code"
                autoCapitalize="none"
                spellCheck={false}
                aria-invalid={Boolean(codeError)}
                aria-describedby={
                  codeError ? 'login-code-hint login-code-error' : 'login-code-hint'
                }
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

            <button
              type="submit"
              disabled={codeForm.formState.isSubmitting || passkeyBusy}
              className="btn-primary w-full"
            >
              {codeForm.formState.isSubmitting ? 'Verificando…' : 'Verificar'}
            </button>

            {showPasskey && (
              <button
                type="button"
                onClick={() => void onUsePasskey()}
                disabled={passkeyBusy || codeForm.formState.isSubmitting}
                className="btn-ghost w-full"
              >
                <KeyIcon />
                {passkeyBusy ? 'Aguardando autenticador…' : 'Usar passkey'}
              </button>
            )}
          </div>
          <div className="auth-card-footer">
            <button
              type="button"
              onClick={onCancel2fa}
              className="font-medium text-slate-700 hover:underline"
            >
              Cancelar
            </button>
          </div>
        </form>
      </main>
    )
  }

  const emailError = credForm.formState.errors.email
  const passwordError = credForm.formState.errors.password
  const busy = credForm.formState.isSubmitting || passkeyBusy || otpBusy
  const submitLabel = mode === 'code' ? 'Enviar código' : 'Entrar'

  return (
    <main className="grid min-h-full place-items-center p-4 sm:p-6">
      <form onSubmit={credForm.handleSubmit(onSubmitCreds)} className="auth-card">
        <div className="auth-card-body">
          <header className="space-y-1 text-center">
            <h1 className="text-xl font-semibold text-slate-900">Entrar</h1>
            <p className="text-sm text-slate-500">Bem-vindo de volta! Entre para continuar.</p>
          </header>

          <button
            type="button"
            onClick={() => void onPasswordlessPasskey()}
            disabled={busy}
            className="btn-ghost relative w-full"
          >
            <KeyIcon />
            {passkeyBusy ? 'Aguardando autenticador…' : 'Entrar com passkey'}
            {lastMethod === 'passkey' && <LastUsedBadge />}
          </button>

          <div className="flex items-center gap-3 text-xs text-slate-400">
            <div className="h-px flex-1 bg-slate-200" />
            <span>ou</span>
            <div className="h-px flex-1 bg-slate-200" />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="login-email" className="block text-sm font-medium text-slate-800">
              E-mail
            </label>
            <input
              id="login-email"
              type="email"
              autoComplete="email webauthn"
              placeholder="voce@empresa.com"
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

          {mode === 'password' ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="login-password"
                  className="block text-sm font-medium text-slate-800"
                >
                  Senha
                </label>
                <Link
                  to="/forgot-password"
                  className="text-xs text-slate-500 hover:text-slate-800 hover:underline"
                >
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
          ) : (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              Vamos enviar um código de 6 dígitos para o seu e-mail. Sem senha.
              {lastMethod === 'code' && <span className="ml-1 font-medium">(Último usado)</span>}
            </p>
          )}

          {submitError && (
            <p role="alert" className="text-sm text-red-600">
              {submitError}
            </p>
          )}

          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy && !passkeyBusy ? 'Aguarde…' : submitLabel}
            {!busy && <span aria-hidden="true">▸</span>}
          </button>

          <button
            type="button"
            onClick={toggleMode}
            disabled={busy}
            className="block w-full text-center text-sm font-medium text-slate-600 hover:text-slate-900 hover:underline"
          >
            {mode === 'password' ? 'Entrar com código por e-mail' : 'Entrar com senha'}
          </button>
        </div>
        <div className="auth-card-footer">
          Não tem uma conta?{' '}
          <Link to="/register" className="font-medium text-slate-900 hover:underline">
            Criar conta
          </Link>
        </div>
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
