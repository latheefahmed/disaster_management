import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminOverview from '../dashboards/admin/AdminOverview'
import { AuthProvider } from '../auth/AuthContext'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('AdminOverview simulation preview', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(
      'user',
      JSON.stringify({ username: 'admin', role: 'admin' })
    )
    localStorage.setItem('token', 'token')

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request, init?: RequestInit) => {
        const url = String(urlIn)
        if (url.endsWith('/admin/scenarios')) {
          if (init?.method === 'POST') return Promise.resolve(createJsonResponse({ id: 2, name: 'S2', status: 'created' }))
          return Promise.resolve(createJsonResponse([{ id: 1, name: 'S1', status: 'created', demand_rows: 0, state_stock_rows: 0, national_stock_rows: 0 }]))
        }
        if (url.includes('/admin/scenarios/1/runs')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/admin/scenarios/1/analysis')) return Promise.resolve(createJsonResponse({ explanations: [], recommendations: [] }))
        if (url.includes('/metadata/states')) return Promise.resolve(createJsonResponse([{ state_code: '10', state_name: 'State 10' }]))
        if (url.includes('/metadata/districts')) return Promise.resolve(createJsonResponse([{ district_code: '101', district_name: 'D101', state_code: '10' }]))
        if (url.includes('/metadata/resources')) return Promise.resolve(createJsonResponse([{ resource_id: 'water', resource_name: 'Water' }]))
        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('updates preview counts when selecting districts/resources', async () => {
    render(
      <AuthProvider>
        <AdminOverview />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('Admin Scenario Studio')).toBeInTheDocument()
      expect(screen.getByText('Preview')).toBeInTheDocument()
    })

    const combos = screen.getAllByRole('combobox')
    fireEvent.change(combos[1], { target: { value: '10' } })
    fireEvent.change(combos[2], { target: { value: '101' } })

    const resourceCheck = screen.getByLabelText('water - Water')
    fireEvent.click(resourceCheck)

    await waitFor(() => {
      expect(screen.getByText(/Districts Selected: 1/)).toBeInTheDocument()
      expect(screen.getByText(/Resources Selected: 1/)).toBeInTheDocument()
    })
  })
})
