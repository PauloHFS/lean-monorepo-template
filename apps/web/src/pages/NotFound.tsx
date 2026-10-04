import { Link } from 'react-router-dom'

export function NotFound() {
  return (
    <main className="min-h-full grid place-items-center p-6">
      <div className="text-center space-y-3">
        <p className="text-sm uppercase tracking-wider text-slate-400">404</p>
        <h1 className="text-2xl font-semibold">Página não encontrada</h1>
        <p className="text-slate-500">Verifique o endereço ou volte ao início.</p>
        <Link to="/dashboard" className="btn-primary inline-block">
          Ir para o Dashboard
        </Link>
      </div>
    </main>
  )
}
