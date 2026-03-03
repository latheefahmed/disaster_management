import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { AuthProvider } from '../auth/AuthContext'
import DistrictOverview from '../dashboards/district/DistrictOverview'
import DistrictRequest from '../dashboards/district/DistrictRequest'
import StateOverview from '../dashboards/state/StateOverview'
import StateRequests from '../dashboards/state/StateRequests'
import NationalOverview from '../dashboards/national/NationalOverview'
import NationalRequests from '../dashboards/national/NationalRequests'
import AdminOverview from '../dashboards/admin/AdminOverview'
import AdminScenarioRunDetails from '../dashboards/admin/AdminScenarioRunDetails'

type Role = 'district' | 'state' | 'national' | 'admin'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

const pageCases = [
  { path: '/district', routePath: '/district', heading: /District Overview/i, element: <DistrictOverview /> },
  { path: '/district/request', routePath: '/district/request', heading: /District Resource Request/i, element: <DistrictRequest /> },
  { path: '/state', routePath: '/state', heading: /State Overview/i, element: <StateOverview /> },
  { path: '/state/requests', routePath: '/state/requests', heading: /State Requests/i, element: <StateRequests /> },
  { path: '/national', routePath: '/national', heading: /National Overview/i, element: <NationalOverview /> },
  { path: '/national/requests', routePath: '/national/requests', heading: /National Escalation/i, element: <NationalRequests /> },
  { path: '/admin', routePath: '/admin', heading: /Admin Scenario Studio/i, element: <AdminOverview /> },
  { path: '/admin/scenarios/1/runs/2', routePath: '/admin/scenarios/:scenarioId/runs/:runId', heading: /Scenario 1 Run 2 Details/i, element: <AdminScenarioRunDetails /> },
] as const

const roles: Role[] = ['district', 'state', 'national', 'admin']

describe('Dashboard page matrix', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request) => {
        const url = String(urlIn)

        if (url.includes('/metadata/states')) return Promise.resolve(createJsonResponse([{ state_code: '10', state_name: 'State 10' }]))
        if (url.includes('/metadata/districts')) return Promise.resolve(createJsonResponse([{ district_code: '101', district_name: 'District 101', state_code: '10' }]))
        if (url.includes('/metadata/resources')) return Promise.resolve(createJsonResponse([{ resource_id: 'water', resource_name: 'Water' }]))

        if (url.includes('/district/allocations')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/unmet')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/demand-mode')) return Promise.resolve(createJsonResponse({ demand_mode: 'baseline_plus_human', ui_mode: 'ai_human' }))
        if (url.includes('/district/requests')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/solver-status')) return Promise.resolve(createJsonResponse({ solver_run_id: 1, status: 'completed', mode: 'live' }))
        if (url.includes('/district/claims')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/consumptions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/returns')) return Promise.resolve(createJsonResponse([]))

        if (url.includes('/state/pool')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/state/pool/transactions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/state/allocations/summary')) return Promise.resolve(createJsonResponse({ solver_run_id: 1, rows: [] }))
        if (url.includes('/state/escalations')) return Promise.resolve(createJsonResponse([]))

        if (url.includes('/national/allocations/summary')) return Promise.resolve(createJsonResponse({ solver_run_id: 1, rows: [] }))
        if (url.includes('/national/escalations')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/national/pool')) return Promise.resolve(createJsonResponse({ total_quantity: 0, rows: [] }))
        if (url.includes('/national/pool/transactions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/national/allocations/stock')) return Promise.resolve(createJsonResponse([]))

        if (url.includes('/admin/scenarios/1/runs/2/summary')) {
          return Promise.resolve(
            createJsonResponse({
              run_id: 2,
              scenario_id: 1,
              status: 'completed',
              totals: {
                allocated_quantity: 100,
                unmet_quantity: 0,
                districts_covered: 1,
                districts_met: 1,
                districts_unmet: 0,
                allocation_rows: 1,
                unmet_rows: 0,
              },
              district_breakdown: [{ district_code: '101', allocated_quantity: 100, unmet_quantity: 0, met: true }],
              allocation_details: [{ district_code: '101', state_code: '10', resource_id: 'water', time: 1, allocated_quantity: 100 }],
              unmet_details: [],
            })
          )
        }
        if (url.endsWith('/admin/scenarios')) return Promise.resolve(createJsonResponse([{ id: 1, name: 'S1', status: 'completed', demand_rows: 1, state_stock_rows: 0, national_stock_rows: 0 }]))
        if (url.includes('/admin/scenarios/1/runs')) return Promise.resolve(createJsonResponse([{ id: 2, status: 'completed', mode: 'scenario' }]))
        if (url.includes('/admin/scenarios/1/analysis')) return Promise.resolve(createJsonResponse({ explanations: [], recommendations: [] }))

        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  const cases: Array<[string, RegExp, Role]> = []
  for (const page of pageCases) {
    for (const role of roles) {
      cases.push([page.path, page.heading, role])
    }
  }

  it.each(cases)('renders %s for role %s', async (path, heading, role) => {
    localStorage.setItem(
      'user',
      JSON.stringify({
        username: `${role}_user`,
        role,
        state_code: '10',
        district_code: '101',
      })
    )
    localStorage.setItem('token', 'token')

    const page = pageCases.find(p => p.path === path)
    if (!page) throw new Error('Missing page case')

    render(
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path={page.routePath} element={page.element} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByText(heading).length).toBeGreaterThan(0)
    })
  })
})
