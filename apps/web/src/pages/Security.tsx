import QRCode from 'qrcode'
import { useState } from 'react'

import { ApiError } from '../api/client'
import { TwoFactorApi } from '../api/endpoints'

type Stage = 'idle' | 'scanning' | 'confirming' | 'enabled'

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
  const [busy, setBusy] = useState(false)

  async function startTotp() {
    setError(null)
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

  async function confirmTotp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const out = await TwoFactorApi.totpConfirm(code)
      if (out.enabled) {
        setRecoveryCodes(out.recovery_codes)
        setStage('enabled')
      } else {
        setError('código inválido')
      }
    } catch (err) {
      setError(humanizeError(err))
    } finally {
      setBusy(false)
    }
  }

  async function registerPasskey() {
    setError(null)
    setBusy(true)
    try {
      const { options, challenge } = await TwoFactorApi.passkeyRegisterOptions()
      // navigator.credentials.create devolve attestation que mandamos de volta
      // para o backend verificar.
      const credential = (await navigator.credentials.create({
        publicKey: options as unknown as PublicKeyCredentialCreationOptions,
      })) as unknown

      // Serializa para base64 (formato que o backend aceita)
      const att = credential as {
        response: { clientDataJSON: ArrayBuffer; attestationObject: ArrayBuffer }
      }
      const payload = {
        challenge,
        client_data_b64: btoa(String.fromCharCode(...new Uint8Array(att.response.clientDataJSON))),
        attestation_b64: btoa(
          String.fromCharCode(...new Uint8Array(att.response.attestationObject)),
        ),
      }
      await TwoFactorApi.passkeyRegisterVerify(payload)
      setError('passkey registrada!')
    } catch (err) {
      setError(humanizeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">Segurança</h1>
        <p className="text-sm text-slate-500">Adicione uma segunda camada além da senha.</p>
      </header>

      <section className="card space-y-4">
        <header className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Autenticador (TOTP)</h2>
          {stage === 'enabled' && (
            <span className="text-xs text-green-600 font-medium">Ativado ✓</span>
          )}
        </header>

        {stage === 'idle' && (
          <button type="button" onClick={startTotp} disabled={busy} className="btn-primary">
            {busy ? 'Gerando…' : 'Configurar TOTP'}
          </button>
        )}

        {stage === 'scanning' && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Escaneie o QR no app (Google Authenticator, 1Password, etc).
            </p>
            <div className="flex flex-col items-center gap-3">
              {qrDataUrl && <img src={qrDataUrl} alt="QR TOTP" className="rounded border" />}
              <details className="text-xs text-slate-500 w-full">
                <summary className="cursor-pointer">
                  Não consegue escanear? Digite manualmente.
                </summary>
                <code className="block mt-2 p-2 bg-slate-100 rounded break-all">{secret}</code>
              </details>
            </div>
            <form onSubmit={confirmTotp} className="flex gap-2">
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                placeholder="123456"
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="input"
              />
              <button type="submit" disabled={busy || code.length !== 6} className="btn-primary">
                Ativar
              </button>
            </form>
          </div>
        )}

        {stage === 'enabled' && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              2FA ativo. Guarde estes códigos de recuperação em local seguro. Cada um serve uma
              única vez.
            </p>
            <pre className="bg-slate-100 rounded p-3 text-xs font-mono grid grid-cols-2 gap-1">
              {recoveryCodes.map((c) => (
                <code key={c}>{c}</code>
              ))}
            </pre>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard.writeText(recoveryCodes.join('\n'))
              }}
              className="btn-ghost text-xs"
            >
              Copiar
            </button>
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
        <button type="button" onClick={registerPasskey} disabled={busy} className="btn-primary">
          {busy ? 'Aguardando autenticador…' : 'Registrar passkey'}
        </button>
      </section>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </main>
  )
}

function humanizeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status} — ${err.message}`
  return (err as Error).message ?? 'erro desconhecido'
}
