import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { AuthProvider } from '../auth/AuthContext'
import DistrictRequest from '../dashboards/district/DistrictRequest'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('DistrictRequest validation', () => {
  beforeEach(() => {
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
          return Promise.resolve(
            createJsonResponse([
              { resource_id: 'R10', resource_name: 'Boats', unit: 'vehicles', ethical_priority: 1 },
            ])
          )
        }

        if (url.includes('/district/allocations')) {
          return Promise.resolve(createJsonResponse([]))
        }

        if (url.includes('/district/requests')) {
          return Promise.resolve(createJsonResponse([]))
        }

        if (url.includes('/district/request-batch') && init?.method === 'POST') {
          return Promise.resolve(createJsonResponse({ status: 'accepted', request_ids: [1], solver_run_id: 1 }))
        }

        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('blocks decimal quantity for countable resources', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <DistrictRequest />
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/Add Resource Request/i)).toBeInTheDocument()
    })

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'R10' } })

    const spinboxes = screen.getAllByRole('spinbutton')
    const quantityInput = spinboxes[1]
    fireEvent.change(quantityInput, { target: { value: '1.5' } })

    fireEvent.click(screen.getByRole('button', { name: 'Add to Request Batch' }))

    await waitFor(() => {
      expect(screen.getByText('Selected resource requires whole-number quantity.')).toBeInTheDocument()
    })
  })
})
