import { useEffect, useState } from 'react'

export type StatePoolEntry = {
  state_code: string
  resource_id: string
  time: number
  quantity: number
  source_district: string
  pooled_at: string
}

const STORAGE_KEY = 'state_resource_pool'

function loadPool(): StatePoolEntry[] {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : []
}

function savePool(pool: StatePoolEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(pool))
}

export function useStatePool() {
  const [pool, setPool] = useState<StatePoolEntry[]>([])

  useEffect(() => {
    setPool(loadPool())
  }, [])

  function addToPool(
    stateCode: string,
    districtCode: string,
    resourceId: string,
    time: number,
    quantity: number
  ) {
    const entry: StatePoolEntry = {
      state_code: stateCode,
      resource_id: resourceId,
      time,
      quantity,
      source_district: districtCode,
      pooled_at: new Date().toISOString()
    }

    const updated = [...pool, entry]
    setPool(updated)
    savePool(updated)
  }

  function getPoolQuantity(
    stateCode: string,
    resourceId: string,
    time: number
  ): number {
    return pool
      .filter(
        p =>
          p.state_code === stateCode &&
          p.resource_id === resourceId &&
          p.time === time
      )
      .reduce((sum, p) => sum + p.quantity, 0)
  }

  function allocateFromPool(
    stateCode: string,
    resourceId: string,
    time: number,
    quantity: number
  ) {
    let remaining = quantity
    const updated: StatePoolEntry[] = []

    for (const p of pool) {
      if (
        p.state_code === stateCode &&
        p.resource_id === resourceId &&
        p.time === time &&
        remaining > 0
      ) {
        const used = Math.min(p.quantity, remaining)
        remaining -= used

        if (p.quantity > used) {
          updated.push({ ...p, quantity: p.quantity - used })
        }
      } else {
        updated.push(p)
      }
    }

    setPool(updated)
    savePool(updated)
  }

  return {
    pool,
    addToPool,
    getPoolQuantity,
    allocateFromPool
  }
}
