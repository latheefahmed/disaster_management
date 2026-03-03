import AppRoutes from './routes/AppRoutes'
import { AuthProvider } from './auth/AuthContext'
import { ScenarioProvider } from './state/scenarioContext'

export default function App() {
  return (
    <AuthProvider>
      <ScenarioProvider>
        <AppRoutes />
      </ScenarioProvider>
    </AuthProvider>
  )
}
