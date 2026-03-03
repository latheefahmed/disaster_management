import { expect, request as playwrightRequest, test } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'

type StatValue = { raw: string; numeric: number | null } | null

type Observation = {
  before?: Record<string, StatValue | number>
  after?: Record<string, StatValue | number>
  api?: Record<string, unknown>
  requestStatus?: number
  runStatus?: number
}

const creds = {
  district: { username: 'district_603', password: 'district123', role: 'district' as const },
  state: { username: 'state_33', password: 'state123', role: 'state' as const },
  national: { username: 'national_admin', password: 'national123', role: 'national' as const },
}

async function loginUi(page: any, c: { username: string; password: string; role: string }) {
  await page.goto('/login')
  await page.getByPlaceholder(/Username/i).fill(c.username)
  await page.getByPlaceholder(/Password/i).fill(c.password)
  await page.locator('select').first().selectOption(c.role)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(new RegExp(`/${c.role}$`))
}

async function loginApi(api: any, username: string, password: string): Promise<string> {
  const res = await api.post('http://127.0.0.1:8000/auth/login', {
    data: { username, password },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return body.access_token
}

async function stat(page: any, label: string): Promise<StatValue> {
  const card = page.locator('div.rounded-xl.border.bg-white.p-4.shadow-sm').filter({ has: page.getByText(label, { exact: true }) }).first()
  if ((await card.count()) === 0) return null
  const raw = ((await card.locator('p.text-xl.font-semibold').first().textContent()) || '').trim()
  const numeric = Number(raw.replace(/[^0-9.-]/g, ''))
  return { raw, numeric: Number.isFinite(numeric) ? numeric : null }
}

async function inventoryCount(page: any): Promise<number> {
  if ((await page.getByText('Resource Inventory', { exact: true }).count()) === 0) return 0
  return await page.locator('button').filter({ hasText: /Total:/ }).count()
}

async function totalTableRows(page: any): Promise<number> {
  const tables = page.locator('table')
  const count = await tables.count()
  let rows = 0
  for (let i = 0; i < count; i++) rows += await tables.nth(i).locator('tbody tr').count()
  return rows
}

test('phase11 reverse engineering observational audit', async ({ page }) => {
  test.setTimeout(180000)
  const outDir = 'test-results/phase11-reverse-audit'
  await mkdir(outDir, { recursive: true })
  const api = await playwrightRequest.newContext()

  const report: Record<string, Observation | string> = {
    timestamp: new Date().toISOString(),
  }

  const districtToken = await loginApi(api, creds.district.username, creds.district.password)
  await loginUi(page, creds.district)

  const districtBefore = {
    finalDemand: await stat(page, 'Total Final Demand'),
    allocated: await stat(page, 'Allocated Resources'),
    unmet: await stat(page, 'Unmet Demand'),
    coverage: await stat(page, 'Coverage %'),
    allocationRows: await totalTableRows(page),
    inventoryRows: await inventoryCount(page),
  }

  await page.screenshot({ path: `${outDir}/district-before.png`, fullPage: true })

  const requestRes = await api.post('http://127.0.0.1:8000/district/request', {
    headers: { Authorization: `Bearer ${districtToken}` },
    data: { resource_id: 'water', time: 1, quantity: 20, priority: 1, urgency: 1, confidence: 1.0, source: 'human' },
  })

  const runRes = await api.post('http://127.0.0.1:8000/district/run', {
    headers: { Authorization: `Bearer ${districtToken}` },
  })

  await page.waitForTimeout(3000)
  await page.reload()
  await page.waitForTimeout(2000)

  const districtAfter = {
    finalDemand: await stat(page, 'Total Final Demand'),
    allocated: await stat(page, 'Allocated Resources'),
    unmet: await stat(page, 'Unmet Demand'),
    coverage: await stat(page, 'Coverage %'),
    allocationRows: await totalTableRows(page),
    inventoryRows: await inventoryCount(page),
  }

  await page.screenshot({ path: `${outDir}/district-after.png`, fullPage: true })

  const districtKpi = await api.get('http://127.0.0.1:8000/district/kpis', { headers: { Authorization: `Bearer ${districtToken}` } })
  const districtStock = await api.get('http://127.0.0.1:8000/district/stock', { headers: { Authorization: `Bearer ${districtToken}` } })

  report.district = {
    requestStatus: requestRes.status(),
    runStatus: runRes.status(),
    before: districtBefore,
    after: districtAfter,
    api: {
      kpiStatus: districtKpi.status(),
      kpiBody: districtKpi.ok() ? await districtKpi.json() : null,
      stockStatus: districtStock.status(),
      stockRows: districtStock.ok() ? (await districtStock.json()).length : 0,
    },
  }

  const stateToken = await loginApi(api, creds.state.username, creds.state.password)
  await loginUi(page, creds.state)
  const stateKpi = await api.get('http://127.0.0.1:8000/state/kpis', { headers: { Authorization: `Bearer ${stateToken}` } })
  const stateStock = await api.get('http://127.0.0.1:8000/state/stock', { headers: { Authorization: `Bearer ${stateToken}` } })

  report.state = {
    before: {
      totalDemand: await stat(page, 'Total District Demand'),
      totalAllocated: await stat(page, 'Total Allocated to Districts'),
      totalUnmet: await stat(page, 'Total Unmet'),
      inventoryRows: await inventoryCount(page),
    },
    api: {
      kpiStatus: stateKpi.status(),
      kpiBody: stateKpi.ok() ? await stateKpi.json() : null,
      stockStatus: stateStock.status(),
      stockRows: stateStock.ok() ? (await stateStock.json()).length : 0,
    },
  }
  await page.screenshot({ path: `${outDir}/state.png`, fullPage: true })

  const nationalToken = await loginApi(api, creds.national.username, creds.national.password)
  await loginUi(page, creds.national)
  const nationalKpi = await api.get('http://127.0.0.1:8000/national/kpis', { headers: { Authorization: `Bearer ${nationalToken}` } })
  const nationalStock = await api.get('http://127.0.0.1:8000/national/stock', { headers: { Authorization: `Bearer ${nationalToken}` } })

  report.national = {
    before: {
      nationalDemand: await stat(page, 'National Demand'),
      nationalStock: await stat(page, 'National Stock'),
      totalUnmet: await stat(page, 'Total Unmet'),
      inventoryRows: await inventoryCount(page),
    },
    api: {
      kpiStatus: nationalKpi.status(),
      kpiBody: nationalKpi.ok() ? await nationalKpi.json() : null,
      stockStatus: nationalStock.status(),
      stockRows: nationalStock.ok() ? (await nationalStock.json()).length : 0,
    },
  }
  await page.screenshot({ path: `${outDir}/national.png`, fullPage: true })

  await writeFile(`${outDir}/observations.json`, JSON.stringify(report, null, 2), 'utf-8')
  await api.dispose()
})
