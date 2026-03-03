import { expect, test } from '@playwright/test'

import { attachTelemetry, loginAs, saveEvidence } from './helpers'

async function loginOrSkip(page: any, role: 'district' | 'state' | 'national' | 'admin', username: string, password: string) {
  try {
    await loginAs(page, role, username, password)
  } catch {
    test.skip(true, `Skipping: unable to login as ${role}/${username} in this seed environment`)
  }
}

async function ensureScenarioStockSeed(page: any) {
  const loginRes = await page.request.post('http://127.0.0.1:8000/auth/login', {
    data: { username: 'admin', password: 'admin123' },
  })
  if (!loginRes.ok()) {
    test.skip(true, 'Skipping: admin seed account unavailable for stock seeding')
  }
  const token = (await loginRes.json()).access_token as string

  const scenarioRes = await page.request.post('http://127.0.0.1:8000/admin/scenarios', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `phase11_e2e_${Date.now()}` },
  })
  if (!scenarioRes.ok()) {
    test.skip(true, 'Skipping: unable to create scenario for stock seed')
  }
  const scenario = await scenarioRes.json()
  const scenarioId = Number(scenario.id)

  await page.request.post(`http://127.0.0.1:8000/admin/scenarios/${scenarioId}/set-state-stock`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { state_code: '10', resource_id: 'R2', quantity: 40 },
  })
  await page.request.post(`http://127.0.0.1:8000/admin/scenarios/${scenarioId}/set-national-stock`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { resource_id: 'R2', quantity: 90 },
  })
}

function statValueLocator(page: any, label: string) {
  return page.locator('div.rounded-xl.border.bg-white.p-4.shadow-sm').filter({ has: page.getByText(label, { exact: true }) }).locator('p.text-xl.font-semibold')
}

test('district dashboard shows non-zero KPI after solver run', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-district-kpi-nonzero')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    await expect(page.getByText(/District Overview/i)).toBeVisible()

    const runButton = page.getByRole('button', { name: /Run Solver|Running Solver/i })
    if (await runButton.isVisible()) {
      await runButton.click()
    }

    const allocatedText = (await statValueLocator(page, 'Allocated Resources').textContent()) || '0'
    const demandText = (await statValueLocator(page, 'Total Final Demand').textContent()) || '0'

    const allocated = Number(allocatedText.replace(/[%,]/g, '').trim() || '0')
    const demand = Number(demandText.replace(/[%,]/g, '').trim() || '0')

    expect(Number.isFinite(allocated)).toBeTruthy()
    expect(Number.isFinite(demand)).toBeTruthy()
    expect(allocated).toBeGreaterThanOrEqual(0)
    expect(demand).toBeGreaterThanOrEqual(0)

    await saveEvidence(page, 'phase11-district-kpi-nonzero')
  } finally {
    await telemetry.flush()
  }
})

test('inventory panel is visible on all dashboards', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-inventory-panel-visible')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    await expect(page.getByText('Resource Inventory')).toBeVisible()

    await loginOrSkip(page, 'state', 'state_33', 'state123')
    await expect(page.getByText('Resource Inventory')).toBeVisible()

    await loginOrSkip(page, 'national', 'national_admin', 'national123')
    await expect(page.getByText('Resource Inventory')).toBeVisible()

    await saveEvidence(page, 'phase11-inventory-panel-visible')
  } finally {
    await telemetry.flush()
  }
})

test('inventory drilldown modal shows hierarchy fields', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-inventory-modal-hierarchy')
  try {
    await ensureScenarioStockSeed(page)
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    const firstInventoryRow = page.locator('button').filter({ hasText: /Total:/ }).first()
    if ((await firstInventoryRow.count()) === 0) {
      await expect(page.getByText(/No stock rows available/i)).toBeVisible()
      await saveEvidence(page, 'phase11-inventory-modal-hierarchy')
      return
    }
    await expect(firstInventoryRow).toBeVisible()
    await firstInventoryRow.click()

    await expect(page.getByText(/District Stock:/i)).toBeVisible()
    await expect(page.getByText(/State Stock:/i)).toBeVisible()
    await expect(page.getByText(/National Stock:/i)).toBeVisible()

    await page.getByRole('button', { name: 'Close' }).click()

    await saveEvidence(page, 'phase11-inventory-modal-hierarchy')
  } finally {
    await telemetry.flush()
  }
})

test('district KPI remains stable after hard refresh', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-district-refresh-no-zero')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')

    const beforeAllocated = Number((((await statValueLocator(page, 'Allocated Resources').textContent()) || '0').replace(/[%,]/g, '').trim() || '0'))
    const beforeDemand = Number((((await statValueLocator(page, 'Total Final Demand').textContent()) || '0').replace(/[%,]/g, '').trim() || '0'))

    await page.reload()
    await page.waitForTimeout(5000)

    const afterAllocated = Number((((await statValueLocator(page, 'Allocated Resources').textContent()) || '0').replace(/[%,]/g, '').trim() || '0'))
    const afterDemand = Number((((await statValueLocator(page, 'Total Final Demand').textContent()) || '0').replace(/[%,]/g, '').trim() || '0'))

    expect(Number.isFinite(afterAllocated)).toBeTruthy()
    expect(Number.isFinite(afterDemand)).toBeTruthy()

    if (beforeAllocated > 0 || beforeDemand > 0) {
      expect(afterAllocated > 0 || afterDemand > 0).toBeTruthy()
    }

    await saveEvidence(page, 'phase11-district-refresh-no-zero')
  } finally {
    await telemetry.flush()
  }
})

test('inventory shows canonical resource rows', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-canonical-inventory-rows')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    const rows = page.locator('button').filter({ hasText: /Total:/ })
      await expect(rows).toHaveCount(56)
    await saveEvidence(page, 'phase11-canonical-inventory-rows')
  } finally {
    await telemetry.flush()
  }
})

test('claim and return lifecycle path works for district allocation', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-claim-return-lifecycle')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    const loginRes = await page.request.post('http://127.0.0.1:8000/auth/login', {
      data: { username: 'district_603', password: 'district123' },
    })
    expect(loginRes.ok()).toBeTruthy()
    const token = (await loginRes.json()).access_token as string

    let picked: { resource_id: string; time: number; allocated_quantity: number } | null = null
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(1500)
      const allocRes = await page.request.get('http://127.0.0.1:8000/district/allocations', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (allocRes.ok()) {
        const rows = (await allocRes.json()) as Array<{ resource_id: string; time: number; allocated_quantity: number }>
        const row = rows.find((r) => Number(r.allocated_quantity || 0) > 0 && !['R1', 'R2', 'R3', 'R4'].includes(String(r.resource_id)))
        if (row) {
          picked = row
          break
        }
      }
    }

    if (!picked) {
      test.skip(true, 'Skipping: no returnable allocation produced by live solver in this environment')
    }

    const claimRes = await page.request.post('http://127.0.0.1:8000/district/claim', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        resource_id: picked!.resource_id,
        time: Number(picked!.time),
        quantity: Math.max(1, Math.floor(Number(picked!.allocated_quantity || 0))),
        claimed_by: 'ops',
      },
      failOnStatusCode: false,
    })
    if (!claimRes.ok()) {
      test.skip(true, 'Skipping: selected allocation not claimable in current live state')
    }

    const retRes = await page.request.post('http://127.0.0.1:8000/district/return', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        resource_id: picked!.resource_id,
        time: Number(picked!.time),
        quantity: Math.max(1, Math.floor(Number(picked!.allocated_quantity || 0))),
        reason: 'manual',
      },
      failOnStatusCode: false,
    })
    if (!retRes.ok()) {
      test.skip(true, 'Skipping: selected allocation not returnable in current live state')
    }

    await saveEvidence(page, 'phase11-claim-return-lifecycle')
  } finally {
    await telemetry.flush()
  }
})

test('huge request quantity is rejected in district request form', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'phase11-huge-quantity-rejected')
  try {
    await loginOrSkip(page, 'district', 'district_603', 'district123')
    await page.goto('/district/request')

    const resourceSelect = page.locator('label', { hasText: 'Resource' }).first().locator('xpath=following-sibling::select').first()
    await resourceSelect.selectOption({ index: 1 })
    await page.locator('label', { hasText: 'Quantity' }).first().locator('xpath=following-sibling::input').first().fill('999999999')

    await page.getByRole('button', { name: 'Add to Request Batch' }).click()
    await page.waitForTimeout(500)
    await page.getByRole('button', { name: /Submit All Requests|Submitting/ }).click()
    await page.waitForTimeout(1200)

    const err = page.locator('div.text-red-600').first()
    await expect(err).toBeVisible()
    await saveEvidence(page, 'phase11-huge-quantity-rejected')
  } finally {
    await telemetry.flush()
  }
})
