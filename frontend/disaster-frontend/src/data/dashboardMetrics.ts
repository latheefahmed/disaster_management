import { useMemo } from 'react'

type MetricsInput<TDemand, TAllocated, TUnmet> = {
  demandRows: TDemand[]
  allocatedRows: TAllocated[]
  unmetRows: TUnmet[]
  demandValue: (row: TDemand) => number
  allocatedValue: (row: TAllocated) => number
  unmetValue: (row: TUnmet) => number
}

function asNumber(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

export function computeDashboardMetrics<TDemand, TAllocated, TUnmet>(
  input: MetricsInput<TDemand, TAllocated, TUnmet>
) {
  const totalDemand = input.demandRows.reduce((sum, row) => sum + asNumber(input.demandValue(row)), 0)
  const totalAllocated = input.allocatedRows.reduce((sum, row) => sum + asNumber(input.allocatedValue(row)), 0)
  const totalUnmet = input.unmetRows.reduce((sum, row) => sum + asNumber(input.unmetValue(row)), 0)
  const coveragePct = totalDemand > 1e-9 ? (totalAllocated / totalDemand) * 100 : 0

  return {
    totalDemand,
    totalAllocated,
    totalUnmet,
    coveragePct,
  }
}

export function useDashboardMetrics<TDemand, TAllocated, TUnmet>(
  input: MetricsInput<TDemand, TAllocated, TUnmet>
) {
  return useMemo(
    () => computeDashboardMetrics(input),
    [input.demandRows, input.allocatedRows, input.unmetRows, input.demandValue, input.allocatedValue, input.unmetValue]
  )
}
