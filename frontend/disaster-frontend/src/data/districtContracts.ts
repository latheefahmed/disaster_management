export type AllocationRow = {
  supply_level: 'district' | 'state' | 'national' | 'mutual_aid_state'
  allocation_source_scope?: 'district' | 'state' | 'neighbor_state' | 'national' | 'unmet' | string
  allocation_source_code?: string | null
  id?: number
  solver_run_id: number
  resource_id: string
  state_code: string
  origin_state_code?: string | null
  origin_district_code?: string | null
  district_code: string
  time: number
  allocated_quantity: number
  claimed_quantity?: number
  consumed_quantity?: number
  returned_quantity?: number
  status?: string
  implied_delay_hours?: number | null
  receipt_confirmed?: boolean
  receipt_time?: string | null
}

export type UnmetRow = {
  resource_id: string
  district_code: string
  time: number
  unmet_demand: number
}

export type ResourceCatalogRow = {
  resource_id: string
  label: string
  unit: string
  resource_name?: string
  canonical_name?: string
}