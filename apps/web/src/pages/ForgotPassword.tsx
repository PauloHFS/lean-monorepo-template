import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { z } from 'zod'

import { AuthApi } from '../api/endpoints'
import { humanizeError } from '../lib/errors'

const forgotSchema = z.object({
  email: z.string().email('e-mail inválido'),
})
type ForgotData = z.infer<typeof forgotSchema>

export function ForgotPassword() {
  const [sent, setSent] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<ForgotData>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })

  async function onSubmit(values: ForgotData) {
    setSubmitError(null)
    try {
      await AuthApi.forgotPassword(values)
      setSent(true)
    } catch (err) {
      setSubmitError(humanizeError(err, 'Não foi possível solicitar a recuperação.'))
    }
  }

  const emailError = form.formState.errors.email

  return (
    <main className="grid min-h-full place-items-center p-4 sm:p-6">
      <div className="auth-card">
        <div className="auth-card-body">
          <header className="space-y-1 text-center">
            <h1 className="text-xl font-semibold text-slate-900">Recuperar senha</h1>
            <p className="text-sm text-slate-500">
              Enviaremos um link de redefinição para o seu e-mail.
            </p>
          </header>

          {sent ? (
            <div className="space-y-4">
              <p role="status" className="text-sm text-green-700">
                Se este endereço estiver cadastrado, você receberá um link para redefinir sua senha
                em instantes.
              </p>
              <Link to="/login" className="btn-ghost w-full">
                Voltar para o login
              </Link>
            </div>
          ) : (
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-1">
                <label htmlFor="forgot-email" className="block text-sm font-medium text-slate-800">
                  E-mail
                </label>
                <input
                  id="forgot-email"
                  type="email"
                  autoComplete="email"
                  aria-invalid={Boolean(emailError)}
                  aria-describedby={emailError ? 'forgot-email-error' : undefined}
                  {...form.register('email')}
                  className="input"
                />
                {emailError && (
                  <span id="forgot-email-error" role="alert" className="block text-xs text-red-600">
                    {emailError.message}
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
                {form.formState.isSubmitting ? 'Enviando…' : 'Enviar link'}
              </button>
            </form>
          )}
        </div>
        <div className="auth-card-footer">
          <Link to="/login" className="font-medium text-slate-900 hover:underline">
            ← Voltar para o login
          </Link>
        </div>
      </div>
    </main>
  )
}
