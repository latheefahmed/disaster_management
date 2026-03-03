import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

function createJsonResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response
}

describe('Navigation and role guards', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()

    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/metadata/states')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/metadata/districts')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/auth/login')) {
          return Promise.resolve(
            createJsonResponse({
              access_token: 'token',
              role: 'district',
              state_code: '10',
              district_code: '101',
            })
          )
        }
        if (url.includes('/district/allocations')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/unmet')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/demand-mode')) return Promise.resolve(createJsonResponse({ demand_mode: 'baseline_plus_human' }))
        if (url.includes('/district/requests')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/solver-status')) return Promise.resolve(createJsonResponse({ solver_run_id: null, status: 'idle', mode: 'live' }))
        if (url.includes('/district/claims')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/consumptions')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/returns')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/metadata/resources')) return Promise.resolve(createJsonResponse([]))
        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('redirects unauthorized /district to login', async () => {
    window.history.pushState({}, '', '/district')
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Disaster Resource Management')).toBeInTheDocument()
    })
  })

  it('navigates to district dashboard after login', async () => {
    window.history.pushState({}, '', '/login')
    render(<App />)

    fireEvent.change(screen.getByPlaceholderText(/Username/i), {
      target: { value: 'district_user' },
    })
    fireEvent.change(screen.getByPlaceholderText(/Password/i), {
      target: { value: 'pw' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))

    await waitFor(() => {
      expect(screen.getByText(/District Overview/i)).toBeInTheDocument()
    })
  })
})
