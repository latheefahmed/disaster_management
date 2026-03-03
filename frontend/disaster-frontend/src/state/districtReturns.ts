import { useState } from 'react'
import { useEffect } from 'react'
import { BACKEND_PATHS } from '../data/backendPaths'
import { apiFetch } from '../data/apiClient'

export type DistrictReturn = {
  district_code: string
  resource_id: string
  time: number
  returned_quantity: number
  reason: 'manual' | 'expiry'
  returned_at: string
  solver_run_id?: number
}

export function useDistrictReturns(enabled: boolean = true) {
  const [returns, setReturns] = useState<DistrictReturn[]>([])

  async function refreshReturns() {
    try {
      const rows = await apiFetch<DistrictReturn[]>(`${BACKEND_PATHS.districtReturns}?page=1&page_size=200`)
      setReturns(Array.isArray(rows) ? rows : [])
    } catch {
      setReturns([])
    }
  }

  useEffect(() => {
    if (!enabled) return
    refreshReturns()
  }, [enabled])

  function getReturnedQuantity(
    districtCode: string,
    resourceId: string,
    time: number,
    solverRunId?: number
  ): number {
    return returns
      .filter(
        r =>
          r.district_code === districtCode &&
          r.resource_id === resourceId &&
          r.time === time &&
          (solverRunId == null || Number(r.solver_run_id) === Number(solverRunId))
      )
      .reduce((sum, r) => sum + r.returned_quantity, 0)
  }

  async function returnResource(
    districtCode: string,
    resourceId: string,
    time: number,
    quantity: number,
    reason: 'manual' | 'expiry',
    solverRunId?: number,
    allocationSourceScope?: string,
    allocationSourceCode?: string,
  ) {
    await apiFetch(BACKEND_PATHS.districtReturn, {
      method: 'POST',
      body: JSON.stringify({
        resource_id: resourceId,
        time,
        quantity,
        reason,
        solver_run_id: solverRunId,
        allocation_source_scope: allocationSourceScope,
        allocation_source_code: allocationSourceCode,
      }),
    })

    await refreshReturns()
  }

  return {
    returns,
    getReturnedQuantity,
    returnResource,
    refreshReturns,
  }
}
