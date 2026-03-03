import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const role = user?.role

  return (
    <div className="min-h-screen text-slate-900">
      <header className="sticky top-0 z-30 border-b border-white/60 bg-white/70 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <h1 className="text-base font-semibold tracking-tight sm:text-lg">
          Disaster Resource Management System
        </h1>

        <nav className="flex flex-wrap items-center gap-3 text-xs text-slate-600 sm:text-sm">
          {role === 'district' && (
            <>
              <Link to="/district" className="hover:text-slate-900">District</Link>
              <Link to="/district/request" className="hover:text-slate-900">District Request</Link>
            </>
          )}
          {role === 'state' && (
            <>
              <Link to="/state" className="hover:text-slate-900">State</Link>
              <Link to="/state/requests" className="hover:text-slate-900">State Requests</Link>
            </>
          )}
          {role === 'national' && (
            <>
              <Link to="/national" className="hover:text-slate-900">National</Link>
              <Link to="/national/requests" className="hover:text-slate-900">National Requests</Link>
            </>
          )}
          {role === 'admin' && (
            <Link to="/admin" className="hover:text-slate-900">Admin</Link>
          )}
          {user && (
            <button
              onClick={() => {
                logout()
                navigate('/login', { replace: true })
              }}
              className="rounded-md border border-slate-300 px-2 py-1 text-slate-700 hover:bg-slate-100"
            >
              Logout
            </button>
          )}
          {user && <span className="text-slate-400">Role: {user.role}</span>}
        </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-6">
        <div className="rounded-2xl border border-white/60 bg-white/60 p-3 shadow-sm backdrop-blur sm:p-4">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
