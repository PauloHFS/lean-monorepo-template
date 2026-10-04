import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { HealthApi, UsersApi } from "../api/endpoints";
import type { EnqueueEmailOut, HealthResponse } from "../api/types";
import { useAuth } from "../lib/auth";

export function Dashboard() {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [enqueueing, setEnqueueing] = useState(false);
  const [lastJob, setLastJob] = useState<EnqueueEmailOut | null>(null);

  useEffect(() => {
    let alive = true;
    HealthApi.check()
      .then((h) => alive && setHealth(h))
      .catch(() => alive && setHealth({ status: "degraded", db: false }));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <main className="min-h-full grid place-items-center text-slate-500">
        carregando…
      </main>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  async function handleEnqueue() {
    if (!user) return;
    setEnqueueing(true);
    try {
      const job = await UsersApi.enqueueEmail({
        to: user.email,
        subject: "Olá do worker",
        body: "Job de exemplo — confirme que o worker processou.",
      });
      setLastJob(job);
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Falha: ${err.status} ${err.message}`);
      }
    } finally {
      setEnqueueing(false);
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <main className="mx-auto max-w-3xl p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-slate-500">Logado como {user.email}</p>
        </div>
        <button type="button" onClick={handleLogout} className="btn-ghost">
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
          <p className="text-sm">
            API: <span className="font-medium">{health.status}</span> · DB:{" "}
            <span className="font-medium">{health.db ? "ok" : "down"}</span>
          </p>
        ) : (
          <p className="text-sm text-slate-500">checando…</p>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="text-base font-semibold">Disparar job no Postgres</h2>
        <p className="text-sm text-slate-500">
          Enfileira um <code>email.send</code> na tabela{" "}
          <code>background_jobs</code>. O worker pega via{" "}
          <code>SELECT … FOR UPDATE SKIP LOCKED</code>.
        </p>
        <button type="button" onClick={handleEnqueue} disabled={enqueueing} className="btn-primary">
          {enqueueing ? "Enfileirando…" : "Enfileirar e-mail"}
        </button>
        {lastJob && (
          <p className="text-sm">
            Último job: <span className="font-mono">{lastJob.job_id}</span> (
            {lastJob.status})
          </p>
        )}
      </section>
    </main>
  );
}