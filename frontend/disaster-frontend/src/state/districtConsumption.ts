import { useEffect, useState } from 'react'
import { BACKEND_PATHS } from '../data/backendPaths'
import { apiFetch } from '../data/apiClient'

export type DistrictConsumption = {
  district_code: string
  resource_id: string
  time: number
  consumed_quantity: number
  consumed_at: string
  solver_run_id?: number
}

export function useDistrictConsumption(enabled: boolean = true) {
  const [consumption, setConsumption] = useState<DistrictConsumption[]>([])

  async function refreshConsumption() {
    try {
      const rows = await apiFetch<DistrictConsumption[]>(`${BACKEND_PATHS.districtConsumptions}?page=1&page_size=200`)
      setConsumption(Array.isArray(rows) ? rows : [])
    } catch {
      setConsumption([])
    }
  }

  useEffect(() => {
    if (!enabled) return
    refreshConsumption()
  }, [enabled])

  async function consumeResource(
    districtCode: string,
    resourceId: string,
    time: number,
    quantity: number,
    solverRunId?: number
  ) {
    await apiFetch(BACKEND_PATHS.districtConsume, {
      method: 'POST',
      body: JSON.stringify({
        resource_id: resourceId,
        time,
        quantity,
        solver_run_id: solverRunId,
      }),
    })

    await refreshConsumption()
  }

  function getConsumedQuantity(
    districtCode: string,
    resourceId: string,
    time: number,
    solverRunId?: number
  ): number {
    return consumption
      .filter(
        c =>
          c.district_code === districtCode &&
          c.resource_id === resourceId &&
          c.time === time &&
          (solverRunId == null || Number(c.solver_run_id) === Number(solverRunId))
      )
      .reduce((sum, c) => sum + c.consumed_quantity, 0)
  }

  return {
    consumption,
    consumeResource,
    getConsumedQuantity,
    refreshConsumption,
  }
}
