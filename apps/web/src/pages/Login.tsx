import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthApi, TwoFactorApi } from "../api/endpoints";
import { useAuth } from "../lib/auth";

const credSchema = z.object({
  email: z.string().email("e-mail inválido"),
  password: z.string().min(8, "mínimo 8 caracteres"),
});
type CredData = z.infer<typeof credSchema>;

const codeSchema = z.object({
  code: z.string().min(6, "código inválido"),
});
type CodeData = z.infer<typeof codeSchema>;

type Pending2fa = {
  token: string;
  methods: string[];
};

function bufToB64Url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function Login() {
  const navigate = useNavigate();
  const { setUser, logout } = useAuth();
  const [step, setStep] = useState<"credentials" | "verify">("credentials");
  const [pending, setPending] = useState<Pending2fa | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const credForm = useForm<CredData>({
    resolver: zodResolver(credSchema),
    defaultValues: { email: "", password: "" },
  });
  const codeForm = useForm<CodeData>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: "" },
  });

  async function onSubmitCreds(values: CredData) {
    setSubmitError(null);
    try {
      const response = await AuthApi.login(values);
      if ("requires_2fa" in response && response.requires_2fa) {
        // type assertion: response vem como {requires_2fa: true, pending_token, methods}
        // mas a union com UserOut só tem requires_2fa.
        const r = response as unknown as {
          pending_token: string;
          methods: string[];
        };
        setPending({ token: r.pending_token, methods: r.methods });
        setStep("verify");
        return;
      }
      // Login sem 2FA — cookie setado. Atualiza contexto e vai.
      const user = response as import("../api/types").UserOut;
      setUser(user);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setSubmitError(humanizeError(err));
    }
  }

  async function onSubmitCode(values: CodeData) {
    if (!pending) return;
    setSubmitError(null);
    try {
      await TwoFactorApi.totpVerify(pending.token, values.code);
      // Cookie foi setado pelo backend. Pega /me para popular o contexto.
      const user = await AuthApi.me();
      setUser(user);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setSubmitError(humanizeError(err));
      codeForm.reset({ code: "" });
    }
  }

  async function onUsePasskey() {
    if (!pending) return;
    setSubmitError(null);
    try {
      const { options, challenge } = await TwoFactorApi.passkeyLoginOptions({
        pending_token: pending.token,
      });

      const credential = (await navigator.credentials.get({
        publicKey: options as unknown as PublicKeyCredentialRequestOptions,
      })) as {
        rawId: ArrayBuffer;
        response: {
          clientDataJSON: ArrayBuffer;
          authenticatorData: ArrayBuffer;
          signature: ArrayBuffer;
        };
      } | null;

      if (!credential) {
        setSubmitError("autenticação cancelada");
        return;
      }

      await TwoFactorApi.passkeyLoginVerify({
        challenge,
        client_data_b64: bufToB64Url(credential.response.clientDataJSON),
        authenticator_b64: bufToB64Url(credential.response.authenticatorData),
        signature_b64: bufToB64Url(credential.response.signature),
        credential_id_b64: bufToB64Url(credential.rawId),
      });

      const user = await AuthApi.me();
      setUser(user);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        setSubmitError("autenticação cancelada pelo usuário");
      } else {
        setSubmitError(humanizeError(err));
      }
    }
  }

  async function onCancel2fa() {
    if (pending) {
      // Limpa o pending no backend pra não vazar tokens
      try {
        await logout();
      } catch {
        /* ignore */
      }
    }
    setPending(null);
    setStep("credentials");
    setSubmitError(null);
    codeForm.reset({ code: "" });
  }

  if (step === "verify" && pending) {
    const showPasskey = pending.methods.includes("passkey");
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
              {...codeForm.register("code")}
              ref={(el) => {
                el?.focus();
              }}
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
            <button
              type="button"
              onClick={onCancel2fa}
              className="btn-ghost flex-1"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={codeForm.formState.isSubmitting}
              className="btn-primary flex-1"
            >
              {codeForm.formState.isSubmitting ? "Verificando…" : "Verificar"}
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
    );
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
            {...credForm.register("email")}
            ref={(el) => {
              el?.focus();
            }}
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
            {...credForm.register("password")}
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
          {credForm.formState.isSubmitting ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}

function humanizeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status} — ${err.message}`;
  return (err as Error).message ?? "erro desconhecido";
}