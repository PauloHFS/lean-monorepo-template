import QRCode from 'qrcode'
import type { FormEvent } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { AuthApi, TwoFactorApi, UsersApi } from '../api/endpoints'
import type { PasskeyItemOut, PasskeyRegisterIn } from '../api/types'
import { useAuth } from '../lib/auth'
import { bytesToBase64Url } from '../lib/base64'
import { humanizeError } from '../lib/errors'
import { toRegistrationOptions } from '../lib/webauthn'

type Stage = 'idle' | 'scanning' | 'enabled'
type CopyStatus = 'idle' | 'copied' | 'failed'

/**
 * Página de Segurança:
 * - Status e gestão de TOTP (ativar, desativar, regenerar recovery codes)
 * - Registro, listagem e remoção de Passkeys (WebAuthn)
 * - Alteração de senha
 * - Exclusão da própria conta
 */
export function Security() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [stage, setStage] = useState<Stage>('idle')
  const [totpEnabled, setTotpEnabled] = useState(false)
  const [recoveryRemaining, setRecoveryRemaining] = useState(0)
  const [passkeys, setPasskeys] = useState<PasskeyItemOut[]>([])
  const [passkeyName, setPasskeyName] = useState('')

  const [secret, setSecret] = useState<string>('')
  const [qrDataUrl, setQrDataUrl] = useState<string>('')
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [copyStatus, setCopyStatus] = useState<CopyStatus>('idle')
  const [savedCodes, setSavedCodes] = useState(false)

  // Troca de senha
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)
  const [pwdError, setPwdError] = useState<string | null>(null)
  const [pwdSuccess, setPwdSuccess] = useState<string | null>(null)

  const loadStatus = useCallback(async () => {
    try {
      const st = await TwoFactorApi.status()
      setTotpEnabled(st.totp_enabled)
      setRecoveryRemaining(st.recovery_codes_remaining)
      setPasskeys(st.passkeys)
      setStage((prev) => {
        if (prev === 'scanning') return prev
        return st.totp_enabled ? 'enabled' : 'idle'
      })
    } catch {
      // Silencioso no mount: os testes E2E mockados que não interceptam /status
      // continuam vendo o estado inicial ('idle') normalmente.
    }
  }, [])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  async function startTotp() {
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const { secret: s, otpauth_uri } = await TwoFactorApi.totpSetup()
      setSecret(s)
      const dataUrl = await QRCode.toDataURL(otpauth_uri, { width: 240 })
      setQrDataUrl(dataUrl)
      setStage('scanning')
    } catch (err) {
      setError(humanizeError(err))
    } finally {
      setBusy(false)
    }
  }

  async function confirmTotp(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const out = await TwoFactorApi.totpConfirm(code)
      if (!out.enabled) {
        setError('Código inválido ou expirado.')
        return
      }
      setRecoveryCodes(out.recovery_codes)
      setTotpEnabled(true)
      setRecoveryRemaining(out.recovery_codes.length)
      setCopyStatus('idle')
      setSavedCodes(false)
      setStage('enabled')
      setSuccess('2FA ativado. Guarde os códigos de recuperação abaixo.')
    } catch (err) {
      if (err instanceof ApiError && [400, 401, 422].includes(err.status)) {
        setError('Código inválido ou expirado.')
      } else {
        setError(humanizeError(err))
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleDisableTotp() {
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      await TwoFactorApi.totpDisable()
      setTotpEnabled(false)
      setRecoveryCodes([])
      setRecoveryRemaining(0)
      setCode('')
      setStage('idle')
      setSuccess('Autenticador TOTP desativado.')
    } catch (err) {
      setError(humanizeError(err, 'Não foi possível desativar o TOTP.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleRegenerateCodes() {
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const out = await TwoFactorApi.totpRegenerateRecoveryCodes()
      setRecoveryCodes(out.recovery_codes)
      setRecoveryRemaining(out.recovery_codes.length)
      setCopyStatus('idle')
      setSavedCodes(false)
      setSuccess('Novos códigos de recuperação gerados. Os anteriores foram invalidados.')
    } catch (err) {
      setError(humanizeError(err, 'Não foi possível regenerar os códigos.'))
    } finally {
      setBusy(false)
    }
  }

  async function registerPasskey() {
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyRegisterOptions()
      const credential = await navigator.credentials.create({
        publicKey: toRegistrationOptions(options),
      })

      if (!(credential instanceof PublicKeyCredential)) {
        setError('Registro cancelado.')
        return
      }

      const resp = credential.response
      if (!(resp instanceof AuthenticatorAttestationResponse)) {
        setError('Resposta inesperada do autenticador.')
        return
      }

      const payload: PasskeyRegisterIn = {
        challenge,
        name: passkeyName.trim() ? passkeyName.trim() : undefined,
        credential: {
          id: credential.id,
          rawId: bytesToBase64Url(credential.rawId),
          type: 'public-key',
          response: {
            clientDataJSON: bytesToBase64Url(resp.clientDataJSON),
            attestationObject: bytesToBase64Url(resp.attestationObject),
            transports: resp.getTransports?.(),
          },
        },
      }
      await TwoFactorApi.passkeyRegisterVerify(payload)
      setPasskeyName('')
      setSuccess('Passkey registrada. Use-a no login direto ou como segundo fator.')
      await loadStatus()
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setError('Registro cancelado pelo usuário.')
      } else {
        setError(humanizeError(err, 'Não foi possível registrar a passkey.'))
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleDeletePasskey(id: string) {
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      await TwoFactorApi.passkeyDelete(id)
      setPasskeys((prev) => prev.filter((p) => p.id !== id))
      setSuccess('Passkey removida.')
    } catch (err) {
      setError(humanizeError(err, 'Não foi possível remover a passkey.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault()
    if (pwdBusy) return
    setPwdError(null)
    setPwdSuccess(null)
    setPwdBusy(true)
    try {
      await AuthApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      setPwdSuccess('Senha alterada com sucesso.')
    } catch (err) {
      setPwdError(humanizeError(err, 'Senha atual incorreta.'))
    } finally {
      setPwdBusy(false)
    }
  }

  async function handleDeleteOwnAccount() {
    if (!user || busy) return
    if (!window.confirm('Tem certeza que deseja excluir sua conta permanentemente?')) return
    setBusy(true)
    try {
      await UsersApi.delete(user.id)
      await logout()
      navigate('/login', { replace: true })
    } catch (err) {
      setError(humanizeError(err, 'Não foi possível excluir sua conta.'))
      setBusy(false)
    }
  }

  async function copyRecoveryCodes() {
    try {
      await navigator.clipboard.writeText(recoveryCodes.join('\n'))
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  function downloadRecoveryCodes() {
    const content = [
      'Códigos de recuperação — Lean Monorepo',
      '',
      ...recoveryCodes,
      '',
      'Cada código serve uma única vez.',
    ].join('\n')
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'codigos-de-recuperacao.txt'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <main className="mx-auto max-w-2xl space-y-8 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">Segurança</h1>
          <p className="text-sm text-slate-500">Adicione uma segunda camada além da senha.</p>
        </div>
        <Link to="/dashboard" className="btn-ghost">
          ← Dashboard
        </Link>
      </header>

      <section className="card space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Autenticador (TOTP)</h2>
          {(stage === 'enabled' || totpEnabled) && (
            <span className="text-sm font-medium text-green-700">Ativado ✓</span>
          )}
        </header>

        {stage === 'idle' && (
          <button
            type="button"
            onClick={() => void startTotp()}
            disabled={busy}
            className="btn-primary w-full sm:w-auto"
          >
            {busy ? 'Gerando…' : 'Configurar TOTP'}
          </button>
        )}

        {stage === 'scanning' && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Escaneie o QR no app (Google Authenticator, 1Password, etc).
            </p>
            <div className="flex flex-col items-center gap-3">
              {qrDataUrl && (
                <img
                  src={qrDataUrl}
                  alt="QR code para configurar o autenticador"
                  width={240}
                  height={240}
                  className="h-auto w-full max-w-[240px] rounded border"
                />
              )}
              <details className="w-full text-xs text-slate-500">
                <summary className="min-h-12 cursor-pointer py-3">
                  Não consegue escanear? Digite manualmente.
                </summary>
                <code className="mt-2 block break-all rounded bg-slate-100 p-2">{secret}</code>
              </details>
            </div>
            <form onSubmit={confirmTotp} className="flex flex-col gap-2 sm:flex-row">
              <div className="space-y-1 sm:flex-1">
                <label htmlFor="totp-code" className="block text-sm text-slate-700">
                  Código de verificação
                </label>
                <input
                  id="totp-code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  autoComplete="one-time-code"
                  placeholder="123456"
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  aria-invalid={error !== null}
                  aria-describedby={error ? 'totp-code-hint page-error' : 'totp-code-hint'}
                  className="input"
                />
                <p id="totp-code-hint" className="text-xs text-slate-500">
                  Digite o código de 6 dígitos gerado pelo app.
                </p>
              </div>
              <button
                type="submit"
                disabled={busy || code.length !== 6}
                className="btn-primary self-end sm:self-auto"
              >
                Ativar
              </button>
            </form>
          </div>
        )}

        {stage === 'enabled' && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Códigos de recuperação disponíveis:{' '}
              <span className="font-semibold text-slate-900">{recoveryRemaining}</span>
            </p>

            {recoveryCodes.length > 0 && (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  Estes códigos serão exibidos apenas uma vez. Baixe ou copie antes de sair desta
                  página. Cada um serve uma única vez.
                </p>
                <p className="text-sm font-medium">Seus códigos de recuperação</p>
                <pre className="grid grid-cols-1 gap-1 rounded bg-slate-100 p-3 font-mono text-xs sm:grid-cols-2">
                  {recoveryCodes.map((c) => (
                    <code key={c} className="break-all">
                      {c}
                    </code>
                  ))}
                </pre>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => void copyRecoveryCodes()}
                    className="btn-ghost w-full sm:w-auto"
                  >
                    Copiar códigos
                  </button>
                  <button
                    type="button"
                    onClick={downloadRecoveryCodes}
                    className="btn-ghost w-full sm:w-auto"
                  >
                    Baixar .txt
                  </button>
                </div>
                {copyStatus === 'copied' && (
                  <p role="status" className="text-sm text-green-700">
                    Códigos copiados.
                  </p>
                )}
                {copyStatus === 'failed' && (
                  <p role="alert" className="text-sm text-red-600">
                    Não foi possível copiar. Use “Baixar .txt”.
                  </p>
                )}
                <label className="flex min-h-12 items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={savedCodes}
                    onChange={(e) => setSavedCodes(e.target.checked)}
                    className="h-5 w-5 rounded border-slate-300"
                  />
                  <span>Salvei os códigos em um local seguro.</span>
                </label>
                {savedCodes && (
                  <p role="status" className="text-sm text-green-700">
                    Tudo certo. Você pode fechar esta página.
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2 pt-2">
              <button
                type="button"
                onClick={() => void handleRegenerateCodes()}
                disabled={busy}
                className="btn-ghost"
              >
                Gerar novos códigos
              </button>
              <button
                type="button"
                onClick={() => void handleDisableTotp()}
                disabled={busy}
                className="btn-ghost text-red-600 hover:bg-red-50"
              >
                Desativar TOTP
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="card space-y-4">
        <header>
          <h2 className="text-base font-semibold">Passkey (sem senha)</h2>
          <p className="text-xs text-slate-500">
            Use sua digital, face ou chave física para entrar direto ou como segundo fator.
          </p>
        </header>

        {passkeys.length > 0 && (
          <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
            {passkeys.map((pk) => (
              <li
                key={pk.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium text-slate-800">{pk.name}</p>
                  <p className="text-xs text-slate-500">
                    Criada em {new Date(pk.created_at).toLocaleDateString('pt-BR')}
                    {pk.last_used_at
                      ? ` · Último uso: ${new Date(pk.last_used_at).toLocaleString('pt-BR')}`
                      : ' · Nunca usada'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleDeletePasskey(pk.id)}
                  disabled={busy}
                  className="btn-ghost text-xs text-red-600 hover:bg-red-50"
                >
                  Remover
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            placeholder="Nome do dispositivo (ex.: MacBook, iPhone)"
            maxLength={100}
            value={passkeyName}
            onChange={(e) => setPasskeyName(e.target.value)}
            aria-label="Nome da passkey"
            className="input sm:flex-1"
          />
          <button
            type="button"
            onClick={() => void registerPasskey()}
            disabled={busy}
            className="btn-primary w-full sm:w-auto"
          >
            {busy ? 'Aguardando autenticador…' : 'Registrar passkey'}
          </button>
        </div>
      </section>

      {success && (
        <p role="status" className="text-sm text-green-700">
          {success}
        </p>
      )}
      {error && (
        <p id="page-error" role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <section className="card space-y-4">
        <header>
          <h2 className="text-base font-semibold">Alterar senha</h2>
          <p className="text-xs text-slate-500">
            Ao alterar sua senha, outras sessões ativas serão desconectadas.
          </p>
        </header>
        <form onSubmit={handleChangePassword} className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="sec-current-password" className="block text-sm text-slate-700">
              Senha atual
            </label>
            <input
              id="sec-current-password"
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="input"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="sec-new-password" className="block text-sm text-slate-700">
              Nova senha (mínimo 8 caracteres)
            </label>
            <input
              id="sec-new-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={72}
              required
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="input"
            />
          </div>
          {pwdError && (
            <p role="alert" className="text-sm text-red-600">
              {pwdError}
            </p>
          )}
          {pwdSuccess && (
            <p role="status" className="text-sm text-green-700">
              {pwdSuccess}
            </p>
          )}
          <button type="submit" disabled={pwdBusy} className="btn-primary w-full sm:w-auto">
            {pwdBusy ? 'Salvando…' : 'Atualizar senha'}
          </button>
        </form>
      </section>

      <section className="card space-y-3 border-red-200">
        <header>
          <h2 className="text-base font-semibold text-red-700">Zona de perigo</h2>
          <p className="text-xs text-slate-500">
            Exclui permanentemente sua conta, sessões e credenciais 2FA.
          </p>
        </header>
        <button
          type="button"
          onClick={() => void handleDeleteOwnAccount()}
          disabled={busy}
          className="btn-ghost text-red-600 ring-red-200 hover:bg-red-50"
        >
          Excluir minha conta
        </button>
      </section>
    </main>
  )
}
