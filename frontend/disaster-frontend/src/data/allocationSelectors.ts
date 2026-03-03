import { loadJSON } from "./jsonLoader"
import { BACKEND_PATHS } from "./backendPaths"

export type AllocationRow = {
  resource_id: string
  district_code: string
  state_code: string
  time: number
  allocated_quantity: number
}

export async function getDistrictAllocations(): Promise<AllocationRow[]> {
  return loadJSON<AllocationRow[]>(BACKEND_PATHS.districtAllocations)
}

export async function getStateAllocations(): Promise<AllocationRow[]> {
  return loadJSON<AllocationRow[]>(BACKEND_PATHS.stateAllocations)
}

export async function getNationalAllocations(): Promise<AllocationRow[]> {
  return loadJSON<AllocationRow[]>(BACKEND_PATHS.nationalAllocations)
}

export function getDistrictAllocatedQuantity(
  rows: AllocationRow[],
  districtCode: string,
  resourceId: string,
  time: number
): number {
  return rows
    .filter(
      r =>
        r.district_code === districtCode &&
        r.resource_id === resourceId &&
        r.time === time
    )
    .reduce((sum, r) => sum + r.allocated_quantity, 0)
}
