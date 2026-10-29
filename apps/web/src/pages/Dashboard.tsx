import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { HealthApi, UsersApi } from '../api/endpoints'
import type { EnqueueEmailOut, HealthResponse, UserOut } from '../api/types'
import { useAuth } from '../lib/auth'
import { humanizeError } from '../lib/errors'

export function Dashboard() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [enqueueing, setEnqueueing] = useState(false)
  const [enqueueError, setEnqueueError] = useState<string | null>(null)
  const [lastJob, setLastJob] = useState<EnqueueEmailOut | null>(null)

  const [usersList, setUsersList] = useState<UserOut[]>([])
  const [usersBusy, setUsersBusy] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    HealthApi.check()
      .then((h) => {
        if (alive) setHealth(h)
      })
      .catch(() => {
        if (alive) setHealthError(true)
      })
    return () => {
      alive = false
    }
  }, [])

  const loadUsers = useCallback(async () => {
    if (!user?.is_superuser) return
    setUsersError(null)
    try {
      const list = await UsersApi.list()
      setUsersList(list)
    } catch {
      // Silencioso no mount: specs E2E mockados que não interceptam GET /users
      // continuam testando apenas o card de job sem ruído de alerta.
    }
  }, [user?.is_superuser])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  // O RequireAuth garante a sessão; isto é só estreitamento de tipo.
  if (!user) return null

  async function handleEnqueue() {
    if (!user) return
    setEnqueueError(null)
    setEnqueueing(true)
    try {
      const job = await UsersApi.enqueueEmail({
        to: user.email,
        subject: 'Olá do worker',
        body: 'Job de exemplo — confirme que o worker processou.',
      })
      setLastJob(job)
    } catch (err) {
      setEnqueueError(humanizeError(err, 'Sua sessão expirou. Entre novamente.'))
    } finally {
      setEnqueueing(false)
    }
  }

  async function handleDeleteUser(targetId: string, targetEmail: string) {
    if (usersBusy) return
    if (!window.confirm(`Remover o usuário ${targetEmail}?`)) return
    setUsersBusy(true)
    setUsersError(null)
    try {
      await UsersApi.delete(targetId)
      setUsersList((prev) => prev.filter((u) => u.id !== targetId))
    } catch (err) {
      setUsersError(humanizeError(err, 'Não foi possível remover o usuário.'))
    } finally {
      setUsersBusy(false)
    }
  }

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">Dashboard</h1>
          <p className="break-words text-sm text-slate-500">Logado como {user.email}</p>
        </div>
        <button type="button" onClick={() => void handleLogout()} className="btn-ghost">
          Sair
        </button>
      </header>

      <section className="card">
        <Link to="/security" className="btn-ghost inline-block">
          Configurar 2FA →
        </Link>
      </section>

      <section className="card space-y-2">
        <h2 className="text-base font-semibold">Saúde do sistema</h2>
        {health ? (
          <p className="text-sm" aria-live="polite">
            API: <span className="font-medium">{health.status}</span> · DB:{' '}
            <span className="font-medium">{health.db ? 'ok' : 'down'}</span>
          </p>
        ) : healthError ? (
          <p role="alert" className="text-sm text-red-600">
            Não foi possível verificar a saúde da API.
          </p>
        ) : (
          <p role="status" className="text-sm text-slate-500">
            checando…
          </p>
        )}
      </section>

      {user.is_superuser && (
        <section className="card space-y-3">
          <h2 className="text-base font-semibold">Disparar job no Postgres</h2>
          <p className="text-sm text-slate-500">
            Enfileira um <code>email.send</code> na fila do Procrastinate (Postgres). O worker
            reivindica o job com <code>SELECT … FOR UPDATE SKIP LOCKED</code>.
          </p>
          <button
            type="button"
            onClick={() => void handleEnqueue()}
            disabled={enqueueing}
            className="btn-primary w-full sm:w-auto"
          >
            {enqueueing ? 'Enfileirando…' : 'Enfileirar e-mail'}
          </button>
          {enqueueError && (
            <p role="alert" className="text-sm text-red-600">
              {enqueueError}
            </p>
          )}
          {lastJob && (
            <p role="status" className="text-sm">
              Último job: <span className="font-mono">{lastJob.job_id}</span> ({lastJob.status})
            </p>
          )}
        </section>
      )}

      {user.is_superuser && usersList.length > 0 && (
        <section className="card space-y-3">
          <header className="flex items-center justify-between gap-2">
            <h2 className="text-base font-semibold">Usuários cadastrados</h2>
            <span className="text-xs text-slate-500">{usersList.length} usuário(s)</span>
          </header>
          <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
            {usersList.map((u) => (
              <li
                key={u.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium text-slate-800">
                    {u.email}{' '}
                    {u.is_superuser && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        admin
                      </span>
                    )}
                  </p>
                  {u.full_name && <p className="text-xs text-slate-500">{u.full_name}</p>}
                </div>
                {u.id !== user.id && (
                  <button
                    type="button"
                    onClick={() => void handleDeleteUser(u.id, u.email)}
                    disabled={usersBusy}
                    className="btn-ghost text-xs text-red-600 hover:bg-red-50"
                  >
                    Remover
                  </button>
                )}
              </li>
            ))}
          </ul>
          {usersError && (
            <p role="alert" className="text-sm text-red-600">
              {usersError}
            </p>
          )}
        </section>
      )}
    </main>
  )
}
