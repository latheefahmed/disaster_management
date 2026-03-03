import { createContext, useContext, useEffect, useState } from "react"

/* ---------- TYPES ---------- */

export type UserRole = "district" | "state" | "national" | "admin"

export type AuthUser = {
  username: string
  role: UserRole
  state_code?: string
  district_code?: string
}

type AuthContextType = {
  user: AuthUser | null
  token: string | null
  isReady: boolean
  districtCode?: string
  stateCode?: string
  login: (u: AuthUser, t: string) => void
  logout: () => void
}

/* ---------- CONTEXT ---------- */

const AuthContext = createContext<AuthContextType>(
  {} as AuthContextType
)

/* ---------- PROVIDER ---------- */

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    const storedUser = localStorage.getItem("user")
    const storedToken = localStorage.getItem("token")

    if (storedUser && storedToken) {
      setUser(JSON.parse(storedUser))
      setToken(storedToken)
    }

    setIsReady(true)
  }, [])

  function login(u: AuthUser, t: string) {
    setUser(u)
    setToken(t)
    localStorage.setItem("user", JSON.stringify(u))
    localStorage.setItem("token", t)
  }

  function logout() {
    setUser(null)
    setToken(null)
    localStorage.removeItem("user")
    localStorage.removeItem("token")
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isReady,
        districtCode: user?.district_code,
        stateCode: user?.state_code,
        login,
        logout
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

/* ---------- HOOK ---------- */

export function useAuth() {
  return useContext(AuthContext)
}
