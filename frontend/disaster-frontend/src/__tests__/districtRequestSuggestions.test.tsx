import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

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

describe('DistrictRequest suggestion UX', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()

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

    vi.stubGlobal(
      'fetch',
      vi.fn((urlIn: string | URL | Request) => {
        const url = String(urlIn)

        if (url.includes('/metadata/resources')) {
          return Promise.resolve(
            createJsonResponse([
              { resource_id: '1', canonical_name: 'water', resource_name: 'Water', ethical_priority: 1 },
            ])
          )
        }

        if (url.includes('/district/allocations')) return Promise.resolve(createJsonResponse([]))
        if (url.includes('/district/requests')) {
          return Promise.resolve(
            createJsonResponse([
              {
                id: 11,
                resource_id: '1',
                time: 1,
                quantity: 10,
                human_priority: null,
                human_urgency: null,
                predicted_priority: 4,
                predicted_urgency: 5,
                prediction_confidence: 0.82,
                prediction_explanation: {
                  features: [
                    { feature: 'unmet', contribution: 0.9, model_type: 'priority' },
                    { feature: 'severity_index', contribution: 0.7, model_type: 'priority' },
                  ],
                },
                source: 'human',
                status: 'pending',
              },
            ])
          )
        }

        return Promise.resolve(createJsonResponse({}))
      })
    )
  })

  it('shows suggested badge, confidence, tooltip and keeps human input editable', async () => {
    render(
      <MemoryRouter initialEntries={['/district/request']}>
        <AuthProvider>
          <Routes>
            <Route path="/district/request" element={<DistrictRequest />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/District Resource Request/i)).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(screen.getByText(/Suggested Priority:/i)).toBeInTheDocument()
      expect(screen.getByText(/Suggested Urgency:/i)).toBeInTheDocument()
      expect(screen.getByText('0.82')).toBeInTheDocument()
    })

    const badge = screen.getByText(/Suggested Priority:/i)
    expect(badge.getAttribute('title') || '').toMatch(/unmet|severity_index/i)

    const priorityInput = screen.getByPlaceholderText('Leave blank for ML suggestion') as HTMLInputElement
    fireEvent.change(priorityInput, { target: { value: '5' } })
    expect(priorityInput.value).toBe('5')
  })
})
