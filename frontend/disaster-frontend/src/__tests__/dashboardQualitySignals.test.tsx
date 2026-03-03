import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { AuthProvider } from '../auth/AuthContext'
import DistrictOverview from '../dashboards/district/DistrictOverview'
import StateOverview from '../dashboards/state/StateOverview'
import StateRequests from '../dashboards/state/StateRequests'
import NationalOverview from '../dashboards/national/NationalOverview'
import NationalRequests from '../dashboards/national/NationalRequests'
import AdminScenarioRunDetails from '../dashboards/admin/AdminScenarioRunDetails'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('Dashboard quality signals', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(
      'user',
      JSON.stringify({
        username: 'district_user',
        role: 'district',
        state_code: '10',
        district_code: '101',
      })
    )
    localStorage.setItem('token', 'token')

    vi.restoreAllMocks()

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request) => {
        const url = String(urlIn)

        if (url.includes('/metadata/resources')) {
          return Promise.resolve(createJsonResponse([{ resource_id: 'water', resource_name: 'Water' }]))
        }

        if (url.includes('/district/allocations')) {
          return Promise.resolve(
            createJsonResponse([
              {
                solver_run_id: 1,
                request_id: 0,
                resource_id: 'water',
                district_code: '101',
                state_code: '10',
                time: 1,
                allocated_quantity: 100,
                is_unmet: false,
              },
            ])
          )
        }
        if (url.includes('/district/unmet')) return Promise.resolve(createJsonResponse([{ district_code: '101', resource_id: 'water', time: 1, unmet_quantity: 10 }]))
        if (url.includes('/district/demand-mode')) return Promise.resolve(createJsonResponse({ demand_mode: 'baseline_plus_human', ui_mode: 'ai_human' }))
        if (url.includes('/district/requests')) {
          return Promise.resolve(
            createJsonResponse([
              {
                id: 1,
                district_code: '101',
                state_code: '10',
                resource_id: 'water',
                time: 1,
                quantity: 80,
                allocated_quantity: 100,
                unmet_quantity: 10,
                status: 'allocated',
                created_at: '2026-02-15T10:00:00Z',
              },
            ])
          )
        }
        if (url.includes('/district/solver-status')) return Promise.resolve(createJsonResponse({ solver_run_id: 1, status: 'completed', mode: 'live' }))
        if (url.includes('/district/claims')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/consumptions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/returns')) return Promise.resolve(createJsonResponse([]))

        if (url.includes('/state/allocations/summary')) {
          return Promise.resolve(
            createJsonResponse({ solver_run_id: 1, rows: [{ district_code: '101', resource_id: 'water', time: 1, allocated_quantity: 100, unmet_quantity: 0, met: true }] })
          )
        }
        if (url.includes('/state/pool/transactions')) {
          return Promise.resolve(
            createJsonResponse([
              {
                id: 1,
                state_code: '10',
                district_code: '101',
                resource_id: 'water',
                time: 1,
                quantity_delta: 20,
                reason: 'district_return:ops',
                actor_role: 'district',
                actor_id: '101',
                created_at: '2026-02-15T10:00:00Z',
              },
            ])
          )
        }
        if (url.includes('/state/pool')) return Promise.resolve(createJsonResponse([{ resource_id: 'water', time: 1, quantity: 20 }]))
        if (url.includes('/state/escalations')) {
          return Promise.resolve(createJsonResponse([{ id: 2, district_code: '101', state_code: '10', resource_id: 'water', quantity: 15, time: 1, status: 'pending' }]))
        }

        if (url.includes('/national/allocations/summary')) {
          return Promise.resolve(
            createJsonResponse({ solver_run_id: 1, rows: [{ state_code: '10', district_code: '101', resource_id: 'water', time: 1, allocated_quantity: 100, unmet_quantity: 0, met: true }] })
          )
        }
        if (url.includes('/national/escalations')) return Promise.resolve(createJsonResponse([{ id: 10, state_code: '10', district_code: '101', resource_id: 'water', quantity: 20, time: 1, status: 'escalated_national' }]))
        if (url.includes('/national/pool')) return Promise.resolve(createJsonResponse({ total_quantity: 50, rows: [] }))
        if (url.includes('/national/pool/transactions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/national/allocations/stock')) return Promise.resolve(createJsonResponse([{ resource_id: 'water', quantity: 1000 }]))

        if (url.includes('/admin/scenarios/1/runs/2/summary')) {
          return Promise.resolve(
            createJsonResponse({
              run_id: 2,
              scenario_id: 1,
              status: 'completed',
              totals: {
                allocated_quantity: 100,
                unmet_quantity: 5,
                districts_covered: 1,
                districts_met: 0,
                districts_unmet: 1,
                allocation_rows: 1,
                unmet_rows: 1,
              },
              district_breakdown: [{ district_code: '101', allocated_quantity: 100, unmet_quantity: 5, met: false }],
              allocation_details: [{ district_code: '101', state_code: '10', resource_id: 'water', time: 1, allocated_quantity: 100 }],
              unmet_details: [{ district_code: '101', state_code: '10', resource_id: 'water', time: 1, unmet_quantity: 5 }],
            })
          )
        }

        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('district shows transparency score', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Allocation Transparency')).toBeInTheDocument()
    })
  })

  it('district shows AI + Human demand mode option', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('AI + Human')).toBeInTheDocument()
    })
  })

  it('district shows request export action', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Export CSV' }).length).toBeGreaterThan(0)
    })
  })

  it('district request summary has coverage column', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Coverage %')).toBeInTheDocument()
    })
  })

  it('state overview shows export actions', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'state_user', role: 'state', state_code: '10' }))
    render(
      <MemoryRouter>
        <AuthProvider>
          <StateOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export Aggregated CSV' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Export Details CSV' })).toBeInTheDocument()
    })
  })

  it('state requests shows grouped/detail exports', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'state_user', role: 'state', state_code: '10' }))
    render(
      <MemoryRouter>
        <AuthProvider>
          <StateRequests />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export Grouped CSV' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Export Details CSV' })).toBeInTheDocument()
    })
  })

  it('national overview shows export csv action', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'national_user', role: 'national' }))
    render(
      <MemoryRouter>
        <AuthProvider>
          <NationalOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export CSV' })).toBeInTheDocument()
    })
  })

  it('national requests shows grouped/detail exports', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'national_user', role: 'national' }))
    render(
      <MemoryRouter>
        <AuthProvider>
          <NationalRequests />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export Grouped CSV' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Export Details CSV' })).toBeInTheDocument()
    })
  })

  it('admin run details shows district export', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'admin_user', role: 'admin' }))
    render(
      <MemoryRouter initialEntries={['/admin/scenarios/1/runs/2']}>
        <AuthProvider>
          <Routes>
            <Route path="/admin/scenarios/:scenarioId/runs/:runId" element={<AdminScenarioRunDetails />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export District CSV' })).toBeInTheDocument()
    })
  })

  it('admin run details shows allocation export', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'admin_user', role: 'admin' }))
    render(
      <MemoryRouter initialEntries={['/admin/scenarios/1/runs/2']}>
        <AuthProvider>
          <Routes>
            <Route path="/admin/scenarios/:scenarioId/runs/:runId" element={<AdminScenarioRunDetails />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export Allocation CSV' })).toBeInTheDocument()
    })
  })

  it('admin run details shows unmet export', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'admin_user', role: 'admin' }))
    render(
      <MemoryRouter initialEntries={['/admin/scenarios/1/runs/2']}>
        <AuthProvider>
          <Routes>
            <Route path="/admin/scenarios/:scenarioId/runs/:runId" element={<AdminScenarioRunDetails />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Export Unmet CSV' })).toBeInTheDocument()
    })
  })

  it('district includes transparency explanation text', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictOverview />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/Transparency score = weighted view/i)).toBeInTheDocument()
    })
  })
})
