import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'

import { ApiError } from '../api/client'
import { AuthApi } from '../api/endpoints'
import { humanizeError } from '../lib/errors'
import { evaluatePasswordStrength, validateNistPasswordClient } from '../lib/password'

const resetSchema = z
  .object({
    token: z.string().trim().min(16, 'token inválido'),
    new_password: z.string().min(8, 'mínimo de 8 caracteres').max(72, 'máximo de 72 caracteres'),
    confirm_password: z.string().min(1, 'confirme a nova senha'),
  })
  .superRefine((data, ctx) => {
    const nistErr = validateNistPasswordClient(data.new_password)
    if (nistErr) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: nistErr,
        path: ['new_password'],
      })
    }
    if (data.new_password !== data.confirm_password) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'as senhas não coincidem',
        path: ['confirm_password'],
      })
    }
  })
type ResetData = z.infer<typeof resetSchema>

export function ResetPassword() {
  const [searchParams] = useSearchParams()
  const initialToken = searchParams.get('token') ?? ''
  const [done, setDone] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<ResetData>({
    resolver: zodResolver(resetSchema),
    defaultValues: { token: initialToken, new_password: '', confirm_password: '' },
  })

  async function onSubmit(values: ResetData) {
    setSubmitError(null)
    try {
      await AuthApi.resetPassword({
        token: values.token,
        new_password: values.new_password,
      })
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setSubmitError('Token inválido ou expirado. Solicite um novo link.')
      } else {
        setSubmitError(humanizeError(err, 'Não foi possível redefinir a senha.'))
      }
    }
  }

  const tokenError = form.formState.errors.token
  const passwordError = form.formState.errors.new_password
  const confirmPasswordError = form.formState.errors.confirm_password
  const watchedPassword = form.watch('new_password')
  const strength = evaluatePasswordStrength(watchedPassword)

  return (
    <main className="grid min-h-full place-items-center p-4 sm:p-6">
      <div className="card w-full max-w-sm space-y-4">
        <header className="space-y-1">
          <h1 className="text-xl font-semibold">Nova senha</h1>
          <p className="text-sm text-slate-500">Defina uma nova senha para sua conta.</p>
        </header>

        {done ? (
          <div className="space-y-4">
            <p role="status" className="text-sm text-green-700">
              Senha redefinida com sucesso! Agora você já pode entrar com a nova senha.
            </p>
            <Link to="/login" className="btn-primary w-full">
              Ir para o login
            </Link>
          </div>
        ) : (
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {!initialToken && (
              <div className="space-y-1">
                <label htmlFor="reset-token" className="block text-sm text-slate-700">
                  Token de recuperação
                </label>
                <input
                  id="reset-token"
                  type="text"
                  autoComplete="off"
                  aria-invalid={Boolean(tokenError)}
                  aria-describedby={tokenError ? 'reset-token-error' : undefined}
                  {...form.register('token')}
                  className="input"
                />
                {tokenError && (
                  <span id="reset-token-error" role="alert" className="block text-xs text-red-600">
                    {tokenError.message}
                  </span>
                )}
              </div>
            )}

            <div className="space-y-1">
              <label htmlFor="reset-password" className="block text-sm text-slate-700">
                Nova senha
              </label>
              <input
                id="reset-password"
                type="password"
                autoComplete="new-password"
                aria-invalid={Boolean(passwordError)}
                aria-describedby={
                  passwordError ? 'reset-password-hint reset-password-error' : 'reset-password-hint'
                }
                {...form.register('new_password')}
                className="input"
              />
              <p id="reset-password-hint" className="text-xs text-slate-500">
                Mínimo de 8 caracteres (recomendado: 12+ caracteres ou frase-senha).
              </p>
              {watchedPassword && (
                <div className="space-y-1 pt-1" aria-live="polite">
                  <div className="flex gap-1">
                    {[1, 2, 3, 4].map((bar) => (
                      <div
                        key={bar}
                        className={`h-1.5 flex-1 rounded-full transition-colors ${
                          strength.score >= bar ? strength.colorClass : 'bg-slate-200'
                        }`}
                      />
                    ))}
                  </div>
                  <p className="text-xs text-slate-600">{strength.label}</p>
                </div>
              )}
              {passwordError && (
                <span id="reset-password-error" role="alert" className="block text-xs text-red-600">
                  {passwordError.message}
                </span>
              )}
            </div>

            <div className="space-y-1">
              <label htmlFor="reset-confirm-password" className="block text-sm text-slate-700">
                Confirmar nova senha
              </label>
              <input
                id="reset-confirm-password"
                type="password"
                autoComplete="new-password"
                aria-invalid={Boolean(confirmPasswordError)}
                aria-describedby={confirmPasswordError ? 'reset-confirm-password-error' : undefined}
                {...form.register('confirm_password')}
                className="input"
              />
              {confirmPasswordError && (
                <span
                  id="reset-confirm-password-error"
                  role="alert"
                  className="block text-xs text-red-600"
                >
                  {confirmPasswordError.message}
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
              disabled={form.formState.isSubmitting}
              className="btn-primary w-full"
            >
              {form.formState.isSubmitting ? 'Salvando…' : 'Redefinir senha'}
            </button>

            <p className="text-center text-sm text-slate-600">
              <Link to="/login" className="font-medium text-brand-600 hover:underline">
                ← Voltar para o login
              </Link>
            </p>
          </form>
        )}
      </div>
    </main>
  )
}
