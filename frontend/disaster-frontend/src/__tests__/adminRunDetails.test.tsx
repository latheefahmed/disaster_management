import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import AdminScenarioRunDetails from '../dashboards/admin/AdminScenarioRunDetails'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('Admin scenario run details route', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('token', 'token')
    localStorage.setItem('user', JSON.stringify({ username: 'admin', role: 'admin' }))

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request) => {
        const url = String(urlIn)
        if (url.includes('/admin/scenarios/1/runs/2/summary')) {
          return Promise.resolve(
            createJsonResponse({
              run_id: 2,
              scenario_id: 1,
              status: 'completed',
              totals: {
                allocated_quantity: 1000,
                unmet_quantity: 120,
                districts_covered: 3,
                districts_met: 2,
                districts_unmet: 1,
                allocation_rows: 5,
                unmet_rows: 2,
              },
              district_breakdown: [
                { district_code: '601', allocated_quantity: 400, unmet_quantity: 0, met: true },
                { district_code: '603', allocated_quantity: 200, unmet_quantity: 120, met: false },
              ],
              allocation_details: [
                { state_code: '33', district_code: '601', resource_id: 'water_liters', time: 1, allocated_quantity: 400 },
              ],
              unmet_details: [
                { state_code: '33', district_code: '603', resource_id: 'water_liters', time: 1, unmet_quantity: 120 },
              ],
            })
          )
        }
        if (url.includes('/metadata/states')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/metadata/districts')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/metadata/resources')) return Promise.resolve(createJsonResponse([]))
        return Promise.resolve(createJsonResponse([]))
      })
    )
  })

  it('loads and renders scenario run breakdown via route', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/scenarios/1/runs/2']}>
        <AuthProvider>
          <Routes>
            <Route
              path="/admin/scenarios/:scenarioId/runs/:runId"
              element={<AdminScenarioRunDetails />}
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/Scenario 1 Run 2 Details/i)).toBeInTheDocument()
      expect(screen.getByText('District Satisfaction')).toBeInTheDocument()
      expect(screen.getByText('Allocation Details')).toBeInTheDocument()
      expect(screen.getByText('Unmet Details')).toBeInTheDocument()
    })
  })
})
