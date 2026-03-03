import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth, UserRole } from "../auth/AuthContext"
import { API_BASE } from "../data/backendPaths"

type State = {
  state_code: string
  state_name: string
}

type District = {
  district_code: string
  district_name: string
  state_code: string
}

export default function Login() {
  const navigate = useNavigate()
  const { login } = useAuth()

  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<UserRole>("district")

  const [stateCode, setStateCode] = useState("")
  const [districtCode, setDistrictCode] = useState("")

  const [states, setStates] = useState<State[]>([])
  const [districts, setDistricts] = useState<District[]>([])

  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  /* ---------------- LOAD STATES ---------------- */

  useEffect(() => {
    fetch(`${API_BASE}/metadata/states`)
      .then(r => r.json())
      .then(setStates)
      .catch(() => setStates([]))
  }, [])

  /* ---------------- LOAD DISTRICTS WHEN STATE CHANGES ---------------- */

  useEffect(() => {
    if (!stateCode) return

    fetch(`${API_BASE}/metadata/districts?state_code=${stateCode}`)
      .then(r => r.json())
      .then(setDistricts)
      .catch(() => setDistricts([]))
  }, [stateCode])

  const stateRequired = role === "district" || role === "state"
  const districtRequired = role === "district"

  const filteredDistricts = useMemo(
    () => districts.filter(d => d.state_code === stateCode),
    [districts, stateCode]
  )

  /* ---------------- SUBMIT ---------------- */

  async function handleSubmit() {
    setError(null)
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          username,
          password
        })
      })

      if (!res.ok) throw new Error("Invalid credentials")

      const data = await res.json()

      // ✅ ONLY CHANGE IS HERE
      login(
        {
          username,
          role: data.role,
          state_code: data.state_code,
          district_code: data.district_code
        },
        data.access_token
      )

      navigate(`/${data.role}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  /* ---------------- UI ---------------- */

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-sky-50 to-violet-50 text-slate-900">
      <div className="mx-auto grid min-h-screen max-w-6xl grid-cols-1 gap-6 px-4 py-8 sm:px-6 lg:grid-cols-2 lg:items-center lg:py-10">
        <section className="relative overflow-hidden rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-600 via-blue-600 to-violet-600 p-6 text-white shadow-xl sm:p-8 lg:p-10">
          <div className="absolute -left-10 -top-10 h-36 w-36 rounded-full bg-white/15" />
          <div className="absolute -bottom-12 -right-8 h-44 w-44 rounded-full bg-white/10" />
          <h1 className="relative text-2xl font-semibold tracking-tight sm:text-3xl">Disaster Resource Management</h1>
          <p className="relative mt-3 max-w-md text-sm text-indigo-100 sm:text-base">
            Unified coordination across district, state, and national operations with live solver-backed allocations.
          </p>
          <div className="relative mt-6 space-y-2 text-sm text-indigo-100">
            <div>• Transparent request → allocation lifecycle</div>
            <div>• Claim / consume / return tracking</div>
            <div>• KPI and stock visibility per governance level</div>
          </div>
        </section>

        <section className="rounded-3xl border border-slate-200/70 bg-white/90 p-6 shadow-lg backdrop-blur sm:p-8">
          <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-slate-500">Use your assigned credentials to continue.</p>

          <div className="mt-5 space-y-4">
            <input
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              placeholder="Username (e.g. district_603)"
              value={username}
              onChange={e => setUsername(e.target.value)}
            />

            <input
              type="password"
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />

            <select
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              value={role}
              onChange={e => {
                setRole(e.target.value as UserRole)
                setStateCode("")
                setDistrictCode("")
              }}
            >
              <option value="district">District</option>
              <option value="state">State</option>
              <option value="national">National</option>
              <option value="admin">Admin</option>
            </select>

            {stateRequired && (
              <select
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                value={stateCode}
                onChange={e => setStateCode(e.target.value)}
              >
                <option value="">Select State</option>
                {states.map(s => (
                  <option key={s.state_code} value={s.state_code}>
                    {s.state_name} ({s.state_code})
                  </option>
                ))}
              </select>
            )}

            {districtRequired && (
              <select
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                value={districtCode}
                onChange={e => setDistrictCode(e.target.value)}
              >
                <option value="">Select District</option>
                {filteredDistricts.map(d => (
                  <option key={d.district_code} value={d.district_code}>
                    {d.district_name} ({d.district_code})
                  </option>
                ))}
              </select>
            )}

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            )}

            <button
              disabled={loading}
              onClick={handleSubmit}
              className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 py-2.5 font-medium text-white shadow-sm transition hover:from-blue-700 hover:to-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Authenticating..." : "Login"}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
