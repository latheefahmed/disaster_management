import { createContext, useContext, useState } from 'react'

export type ScenarioId =
  | 'S1'
  | 'S3'
  | 'S4'
  | 'S5'
  | 'S6'
  | 'S12'

type ScenarioContextType = {
  scenario: ScenarioId
  setScenario: (s: ScenarioId) => void
}

const ScenarioContext = createContext<ScenarioContextType | null>(null)

export function ScenarioProvider({ children }: { children: React.ReactNode }) {
  const [scenario, setScenario] = useState<ScenarioId>('S1')

  return (
    <ScenarioContext.Provider value={{ scenario, setScenario }}>
      {children}
    </ScenarioContext.Provider>
  )
}

export function useScenario() {
  const ctx = useContext(ScenarioContext)
  if (!ctx) throw new Error('useScenario must be used within ScenarioProvider')
  return ctx
}
