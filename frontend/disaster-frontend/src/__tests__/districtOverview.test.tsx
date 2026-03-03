import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DistrictOverview from '../dashboards/district/DistrictOverview'
import { AuthProvider } from '../auth/AuthContext'
import { MemoryRouter } from 'react-router-dom'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('DistrictOverview state display and actions', () => {
  let stockFetchCount = 0

  beforeEach(() => {
    stockFetchCount = 0
    localStorage.clear()
    localStorage.setItem(
      'user',
      JSON.stringify({
        username: 'district_user',
        role: 'district',
        district_code: '101',
        state_code: '10',
      })
    )
    localStorage.setItem('token', 'token')

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request, init?: RequestInit) => {
        const url = String(urlIn)
        if (url.includes('/metadata/resources')) {
          return Promise.resolve(createJsonResponse([
            { resource_id: 'R2', resource_name: 'Rice (kg)', category: 'FOOD_WATER', class: 'consumable' },
            { resource_id: 'R10', resource_name: 'Boats', category: 'VEHICLE', class: 'non_consumable', is_returnable: true },
          ]))
        }
        if (url.includes('/district/allocations')) {
          return Promise.resolve(
            createJsonResponse([
              {
                id: 1,
                solver_run_id: 1,
                request_id: 0,
                resource_id: 'R2',
                district_code: '101',
                state_code: '10',
                time: 1,
                allocated_quantity: 100,
                claimed_quantity: 0,
                consumed_quantity: 0,
                returned_quantity: 0,
                status: 'allocated',
              },
              {
                id: 2,
                solver_run_id: 1,
                request_id: 0,
                resource_id: 'R10',
                district_code: '101',
                state_code: '10',
                time: 1,
                allocated_quantity: 10,
                claimed_quantity: 10,
                consumed_quantity: 0,
                returned_quantity: 10,
                status: 'RETURNED',
              },
            ])
          )
        }
        if (url.includes('/district/unmet')) {
          return Promise.resolve(createJsonResponse([{ id: 1, solver_run_id: 1, resource_id: 'R2', district_code: '101', time: 1, unmet_quantity: 10 }]))
        }
        if (url.includes('/district/stock')) {
          stockFetchCount += 1
          return Promise.resolve(createJsonResponse([{ resource_id: 'R2', district_stock: 25, state_stock: 40, national_stock: 90, in_transit: 0, available_stock: 155 }]))
        }
        if (url.includes('/district/demand-mode')) {
          if (init?.method === 'PUT') return Promise.resolve(createJsonResponse({ district_code: '101', demand_mode: 'human_only' }))
          return Promise.resolve(createJsonResponse({ demand_mode: 'baseline_plus_human' }))
        }
        if (url.includes('/district/requests')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/solver-status')) return Promise.resolve(createJsonResponse({ solver_run_id: 1, status: 'completed', mode: 'live' }))
        if (url.includes('/district/claims')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/consumptions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/returns')) return Promise.resolve(createJsonResponse([]))

        if (url.includes('/district/claim') && init?.method === 'POST') return Promise.resolve(createJsonResponse({ status: 'ok', id: 1 }))
        if (url.includes('/district/consume') && init?.method === 'POST') return Promise.resolve(createJsonResponse({ status: 'ok', id: 2 }))
        if (url.includes('/district/return') && init?.method === 'POST') return Promise.resolve(createJsonResponse({ status: 'ok', id: 3 }))
        if (url.includes('/district/run') && init?.method === 'POST') return Promise.resolve(createJsonResponse({ status: 'accepted', solver_run_id: 2 }))

        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('renders key stats and allows claim click path', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/District Overview/i)).toBeInTheDocument()
      expect(screen.getByText('Allocated Resources')).toBeInTheDocument()
      expect(screen.getByText('Unmet Demand')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Resource Stocks/i }))

    await waitFor(() => {
      expect(screen.getByText('Rice (kg)')).toBeInTheDocument()
      expect(screen.getByText('155')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Allocations' }))

    const claimBtn = await screen.findByRole('button', { name: 'Claim' })
    fireEvent.click(claimBtn)

    expect(screen.queryByRole('button', { name: 'Return' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Returned to Pool' })).toBeDisabled()

    const beforeRunStockFetches = stockFetchCount
    fireEvent.click(screen.getByRole('button', { name: /Run Solver/i }))

    await waitFor(() => {
      expect(screen.getByText(/Last refresh:/i)).toBeInTheDocument()
      expect(stockFetchCount).toBeGreaterThan(beforeRunStockFetches)
    })
  })
})
