import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { ApiError } from '../api/client'
import { AuthApi, TwoFactorApi } from '../api/endpoints'
import type { PasskeyAuthenticationCredential } from '../api/types'
import { useAuth } from '../lib/auth'
import { bytesToBase64Url } from '../lib/base64'
import { toAuthenticationOptions } from '../lib/webauthn'

const credSchema = z.object({
  email: z.string().email('e-mail inválido'),
  password: z.string().min(8, 'mínimo 8 caracteres'),
})
type CredData = z.infer<typeof credSchema>

const codeSchema = z.object({
  code: z.string().min(6, 'código inválido'),
})
type CodeData = z.infer<typeof codeSchema>

type Pending2fa = {
  token: string
  methods: string[]
}

export function Login() {
  const navigate = useNavigate()
  const { setUser, logout } = useAuth()
  const [step, setStep] = useState<'credentials' | 'verify'>('credentials')
  const [pending, setPending] = useState<Pending2fa | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

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
      // Login sem 2FA — cookie setado. Atualiza contexto e vai.
      if (!response.user) {
        setSubmitError('sessão inválida — tente novamente')
        return
      }
      setUser(response.user)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setSubmitError(humanizeError(err))
    }
  }

  async function onSubmitCode(values: CodeData) {
    if (!pending) return
    setSubmitError(null)
    try {
      await TwoFactorApi.totpVerify(pending.token, values.code)
      // Cookie foi setado pelo backend. Pega /me para popular o contexto.
      const user = await AuthApi.me()
      setUser(user)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setSubmitError(humanizeError(err))
      codeForm.reset({ code: '' })
    }
  }

  async function onUsePasskey() {
    if (!pending) return
    setSubmitError(null)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyLoginOptions({
        pending_token: pending.token,
      })

      const credential = await navigator.credentials.get({
        publicKey: toAuthenticationOptions(options),
      })

      if (!(credential instanceof PublicKeyCredential)) {
        setSubmitError('autenticação cancelada')
        return
      }

      const resp = credential.response
      if (!(resp instanceof AuthenticatorAssertionResponse)) {
        setSubmitError('resposta inesperada do autenticador')
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

      const user = await AuthApi.me()
      setUser(user)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setSubmitError('autenticação cancelada pelo usuário')
      } else {
        setSubmitError(humanizeError(err))
      }
    }
  }

  async function onCancel2fa() {
    if (pending) {
      // Limpa o pending no backend pra não vazar tokens
      try {
        await logout()
      } catch {
        /* ignore */
      }
    }
    setPending(null)
    setStep('credentials')
    setSubmitError(null)
    codeForm.reset({ code: '' })
  }

  if (step === 'verify' && pending) {
    const showPasskey = pending.methods.includes('passkey')
    return (
      <main className="min-h-full grid place-items-center p-6">
        <form
          onSubmit={codeForm.handleSubmit(onSubmitCode)}
          className="card w-full max-w-sm space-y-4"
        >
          <header className="space-y-1">
            <h1 className="text-xl font-semibold">Verificação em duas etapas</h1>
            <p className="text-sm text-slate-500">
              Digite o código do seu app autenticador (ou um código de recuperação).
            </p>
          </header>

          <label className="block text-sm">
            <span className="text-slate-700">Código</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              {...codeForm.register('code')}
              className="input mt-1"
            />
            {codeForm.formState.errors.code && (
              <span role="alert" className="text-xs text-red-600 mt-1 block">
                {codeForm.formState.errors.code.message}
              </span>
            )}
          </label>

          {submitError && (
            <p role="alert" className="text-sm text-red-600">
              {submitError}
            </p>
          )}

          <div className="flex gap-2">
            <button type="button" onClick={onCancel2fa} className="btn-ghost flex-1">
              Cancelar
            </button>
            <button
              type="submit"
              disabled={codeForm.formState.isSubmitting}
              className="btn-primary flex-1"
            >
              {codeForm.formState.isSubmitting ? 'Verificando…' : 'Verificar'}
            </button>
          </div>

          {showPasskey && (
            <button
              type="button"
              onClick={onUsePasskey}
              disabled={codeForm.formState.isSubmitting}
              className="btn-ghost w-full"
            >
              Usar passkey
            </button>
          )}
        </form>
      </main>
    )
  }

  return (
    <main className="min-h-full grid place-items-center p-6">
      <form
        onSubmit={credForm.handleSubmit(onSubmitCreds)}
        className="card w-full max-w-sm space-y-4"
      >
        <header className="space-y-1">
          <h1 className="text-xl font-semibold">Entrar</h1>
          <p className="text-sm text-slate-500">Use sua conta para acessar.</p>
        </header>

        <label className="block text-sm">
          <span className="text-slate-700">E-mail</span>
          <input
            type="email"
            autoComplete="email"
            {...credForm.register('email')}
            className="input mt-1"
          />
          {credForm.formState.errors.email && (
            <span role="alert" className="text-xs text-red-600 mt-1 block">
              {credForm.formState.errors.email.message}
            </span>
          )}
        </label>

        <label className="block text-sm">
          <span className="text-slate-700">Senha</span>
          <input
            type="password"
            autoComplete="current-password"
            {...credForm.register('password')}
            className="input mt-1"
          />
          {credForm.formState.errors.password && (
            <span role="alert" className="text-xs text-red-600 mt-1 block">
              {credForm.formState.errors.password.message}
            </span>
          )}
        </label>

        {submitError && (
          <p role="alert" className="text-sm text-red-600">
            {submitError}
          </p>
        )}

        <button
          type="submit"
          disabled={credForm.formState.isSubmitting}
          className="btn-primary w-full"
        >
          {credForm.formState.isSubmitting ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </main>
  )
}

function humanizeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status} — ${err.message}`
  return (err as Error).message ?? 'erro desconhecido'
}
