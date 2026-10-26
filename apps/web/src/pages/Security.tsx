import QRCode from 'qrcode'
import type { FormEvent } from 'react'
import { useState } from 'react'

import { ApiError } from '../api/client'
import { TwoFactorApi } from '../api/endpoints'
import type { PasskeyRegisterIn } from '../api/types'
import { bytesToBase64Url } from '../lib/base64'
import { humanizeError } from '../lib/errors'
import { toRegistrationOptions } from '../lib/webauthn'

type Stage = 'idle' | 'scanning' | 'enabled'
type CopyStatus = 'idle' | 'copied' | 'failed'

/**
 * Página de Segurança: setup TOTP + registro de passkey.
 *
 * TOTP flow:
 *   idle → POST /totp/setup → mostra QR + secret manual → usuário digita code
 *       → POST /totp/confirm → enabled (com recovery codes)
 *
 * Passkey flow:
 *   navigator.credentials.create() → POST /passkey/register/options
 *   → POST /passkey/register/verify
 */
export function Security() {
  const [stage, setStage] = useState<Stage>('idle')
  const [secret, setSecret] = useState<string>('')
  const [qrDataUrl, setQrDataUrl] = useState<string>('')
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [copyStatus, setCopyStatus] = useState<CopyStatus>('idle')
  const [savedCodes, setSavedCodes] = useState(false)

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

  async function registerPasskey() {
    if (busy) return
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyRegisterOptions()
      // navigator.credentials.create devolve attestation que mandamos de volta
      // para o backend verificar.
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
      setSuccess('Passkey registrada. Use-a como segundo fator no próximo login.')
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
      <header>
        <h1 className="text-xl font-semibold sm:text-2xl">Segurança</h1>
        <p className="text-sm text-slate-500">Adicione uma segunda camada além da senha.</p>
      </header>

      <section className="card space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Autenticador (TOTP)</h2>
          {stage === 'enabled' && (
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
      </section>

      <section className="card space-y-3">
        <header>
          <h2 className="text-base font-semibold">Passkey (sem senha)</h2>
          <p className="text-xs text-slate-500">
            Use sua digital, face ou chave física. Sem código pra digitar.
          </p>
        </header>
        <button
          type="button"
          onClick={() => void registerPasskey()}
          disabled={busy}
          className="btn-primary w-full sm:w-auto"
        >
          {busy ? 'Aguardando autenticador…' : 'Registrar passkey'}
        </button>
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
    </main>
  )
}
