import { useEffect, useState } from 'react'
import { BACKEND_PATHS } from '../data/backendPaths'
import { apiFetch } from '../data/apiClient'

export type DistrictClaim = {
  district_code: string
  resource_id: string
  time: number
  claimed_quantity: number
  claimed_at: string
  claimed_by: string
  solver_run_id?: number
}

export function useDistrictClaims(enabled: boolean = true) {
  const [claims, setClaims] = useState<DistrictClaim[]>([])

  async function refreshClaims() {
    try {
      const rows = await apiFetch<DistrictClaim[]>(`${BACKEND_PATHS.districtClaims}?page=1&page_size=200`)
      setClaims(Array.isArray(rows) ? rows : [])
    } catch {
      setClaims([])
    }
  }

  useEffect(() => {
    if (!enabled) return
    refreshClaims()
  }, [enabled])

  function getClaim(
    districtCode: string,
    resourceId: string,
    time: number,
    solverRunId?: number
  ): DistrictClaim | undefined {
    return claims.find(
      c =>
        c.district_code === districtCode &&
        c.resource_id === resourceId &&
        c.time === time &&
        (solverRunId == null || Number(c.solver_run_id) === Number(solverRunId))
    )
  }

  async function claimResource(
    districtCode: string,
    resourceId: string,
    time: number,
    quantity: number,
    claimedBy: string,
    solverRunId?: number
  ) {
    await apiFetch(BACKEND_PATHS.districtClaim, {
      method: 'POST',
      body: JSON.stringify({
        resource_id: resourceId,
        time,
        quantity,
        claimed_by: claimedBy,
        solver_run_id: solverRunId,
      }),
    })

    await refreshClaims()
  }

  return {
    claims,
    getClaim,
    claimResource,
    refreshClaims,
  }
}
