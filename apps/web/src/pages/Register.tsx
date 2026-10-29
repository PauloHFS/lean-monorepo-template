import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router'
import { z } from 'zod'

import { ApiError } from '../api/client'
import { AuthApi } from '../api/endpoints'
import { useAuth } from '../lib/auth'
import { humanizeError } from '../lib/errors'

const registerSchema = z
  .object({
    full_name: z.string().trim().max(200, 'máximo de 200 caracteres').optional(),
    email: z.string().email('e-mail inválido'),
    password: z.string().min(8, 'mínimo de 8 caracteres').max(72, 'máximo de 72 caracteres'),
    confirm_password: z.string().min(1, 'confirme sua senha'),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: 'as senhas não coincidem',
    path: ['confirm_password'],
  })
type RegisterData = z.infer<typeof registerSchema>

export function Register() {
  const navigate = useNavigate()
  const { user, setUser } = useAuth()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<RegisterData>({
    resolver: zodResolver(registerSchema),
    defaultValues: { full_name: '', email: '', password: '', confirm_password: '' },
  })

  if (user) return <Navigate to="/dashboard" replace />

  async function onSubmit(values: RegisterData) {
    setSubmitError(null)
    try {
      await AuthApi.register({
        email: values.email,
        password: values.password,
        full_name: values.full_name ? values.full_name : null,
      })
      const loginRes = await AuthApi.login({
        email: values.email,
        password: values.password,
      })
      if (loginRes.user) {
        setUser(loginRes.user)
        navigate('/dashboard', { replace: true })
        return
      }
      navigate('/login', { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setSubmitError('Este e-mail já está cadastrado.')
      } else {
        setSubmitError(humanizeError(err, 'Não foi possível criar sua conta.'))
      }
    }
  }

  const nameError = form.formState.errors.full_name
  const emailError = form.formState.errors.email
  const passwordError = form.formState.errors.password
  const confirmPasswordError = form.formState.errors.confirm_password

  return (
    <main className="grid min-h-full place-items-center p-4 sm:p-6">
      <form onSubmit={form.handleSubmit(onSubmit)} className="card w-full max-w-sm space-y-4">
        <header className="space-y-1">
          <h1 className="text-xl font-semibold">Criar conta</h1>
          <p className="text-sm text-slate-500">Cadastre-se para acessar o sistema.</p>
        </header>

        <div className="space-y-1">
          <label htmlFor="register-name" className="block text-sm text-slate-700">
            Nome (opcional)
          </label>
          <input
            id="register-name"
            type="text"
            autoComplete="name"
            aria-invalid={Boolean(nameError)}
            aria-describedby={nameError ? 'register-name-error' : undefined}
            {...form.register('full_name')}
            className="input"
          />
          {nameError && (
            <span id="register-name-error" role="alert" className="block text-xs text-red-600">
              {nameError.message}
            </span>
          )}
        </div>

        <div className="space-y-1">
          <label htmlFor="register-email" className="block text-sm text-slate-700">
            E-mail
          </label>
          <input
            id="register-email"
            type="email"
            autoComplete="email"
            aria-invalid={Boolean(emailError)}
            aria-describedby={emailError ? 'register-email-error' : undefined}
            {...form.register('email')}
            className="input"
          />
          {emailError && (
            <span id="register-email-error" role="alert" className="block text-xs text-red-600">
              {emailError.message}
            </span>
          )}
        </div>

        <div className="space-y-1">
          <label htmlFor="register-password" className="block text-sm text-slate-700">
            Senha
          </label>
          <input
            id="register-password"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(passwordError)}
            aria-describedby={
              passwordError
                ? 'register-password-hint register-password-error'
                : 'register-password-hint'
            }
            {...form.register('password')}
            className="input"
          />
          <p id="register-password-hint" className="text-xs text-slate-500">
            Mínimo de 8 caracteres.
          </p>
          {passwordError && (
            <span id="register-password-error" role="alert" className="block text-xs text-red-600">
              {passwordError.message}
            </span>
          )}
        </div>

        <div className="space-y-1">
          <label htmlFor="register-confirm-password" className="block text-sm text-slate-700">
            Confirmar senha
          </label>
          <input
            id="register-confirm-password"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(confirmPasswordError)}
            aria-describedby={confirmPasswordError ? 'register-confirm-password-error' : undefined}
            {...form.register('confirm_password')}
            className="input"
          />
          {confirmPasswordError && (
            <span
              id="register-confirm-password-error"
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

        <button type="submit" disabled={form.formState.isSubmitting} className="btn-primary w-full">
          {form.formState.isSubmitting ? 'Criando conta…' : 'Criar conta'}
        </button>

        <p className="text-center text-sm text-slate-600">
          Já tem uma conta?{' '}
          <Link to="/login" className="font-medium text-brand-600 hover:underline">
            Entrar
          </Link>
        </p>
      </form>
    </main>
  )
}
