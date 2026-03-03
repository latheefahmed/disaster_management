import { expect, request as playwrightRequest, test } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'

const OUT_DIR = 'test-results/phase11-reverse-audit'
const OBS_FILE = `${OUT_DIR}/observations.json`

type C = { username: string; password: string; role: 'district' | 'state' | 'national' }
const creds: Record<'district'|'state'|'national', C> = {
  district: { username: 'district_603', password: 'district123', role: 'district' },
  state: { username: 'state_33', password: 'state123', role: 'state' },
  national: { username: 'national_admin', password: 'national123', role: 'national' },
}

async function savePartial(key: string, value: any) {
  await mkdir(OUT_DIR, { recursive: true })
  let current: any = { timestamp: new Date().toISOString() }
  try {
    current = JSON.parse(await readFile(OBS_FILE, 'utf-8'))
  } catch {}
  current[key] = value
  await writeFile(OBS_FILE, JSON.stringify(current, null, 2), 'utf-8')
}

async function loginUi(page: any, c: C) {
  await page.goto('/login')
  await page.getByPlaceholder(/Username/i).fill(c.username)
  await page.getByPlaceholder(/Password/i).fill(c.password)
  await page.locator('select').first().selectOption(c.role)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(new RegExp(`/${c.role}$`))
}

async function loginApi(username: string, password: string) {
  const api = await playwrightRequest.newContext()
  const res = await api.post('http://127.0.0.1:8000/auth/login', { data: { username, password }, timeout: 10000 })
  expect(res.ok()).toBeTruthy()
  const token = (await res.json()).access_token as string
  return { api, token }
}

async function stat(page: any, label: string) {
  const card = page.locator('div.rounded-xl.border.bg-white.p-4.shadow-sm').filter({ has: page.getByText(label, { exact: true }) }).first()
  if ((await card.count()) === 0) return null
  const raw = ((await card.locator('p.text-xl.font-semibold').first().textContent()) || '').trim()
  const n = Number(raw.replace(/[^0-9.-]/g, ''))
  return { raw, numeric: Number.isFinite(n) ? n : null }
}

async function inventoryRows(page: any) {
  if ((await page.getByText('Resource Inventory', { exact: true }).count()) === 0) return 0
  return await page.locator('button').filter({ hasText: /Total:/ }).count()
}

async function settleDashboard(page: any, ms: number) {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(ms)
}

async function probe(api: any, token: string, path: string) {
  const start = Date.now()
  try {
    const res = await api.get(`http://127.0.0.1:8000${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 15000,
    })
    return { path, status: res.status(), ms: Date.now() - start }
  } catch {
    return { path, status: 'timeout_or_error', ms: Date.now() - start }
  }
}

test('district behavioral reconstruction', async ({ page }) => {
  test.setTimeout(120000)
  await loginUi(page, creds.district)
  await settleDashboard(page, 5000)
  const { api, token } = await loginApi(creds.district.username, creds.district.password)

  const before = {
    finalDemand: await stat(page, 'Total Final Demand'),
    allocated: await stat(page, 'Allocated Resources'),
    unmet: await stat(page, 'Unmet Demand'),
    coverage: await stat(page, 'Coverage %'),
    inventoryRows: await inventoryRows(page),
    allocationRows: await page.locator('table tbody tr').count(),
  }

  let requestStatus: number | string = 'not_attempted'
  let runStatus: number | string = 'not_attempted'

  try {
    const requestRes = await api.post('http://127.0.0.1:8000/district/request', {
      headers: { Authorization: `Bearer ${token}` },
      data: { resource_id: 'water', time: 1, quantity: 10, priority: 1, urgency: 1, confidence: 1.0, source: 'human' },
      timeout: 10000,
      failOnStatusCode: false,
    })
    requestStatus = requestRes.status()
  } catch {
    requestStatus = 'timeout_or_error'
  }

  try {
    const runRes = await api.post('http://127.0.0.1:8000/district/run', {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 10000,
      failOnStatusCode: false,
    })
    runStatus = runRes.status()
  } catch {
    runStatus = 'timeout_or_error'
  }

  await page.waitForTimeout(2500)
  await page.reload()
  await settleDashboard(page, 5000)

  const after = {
    url: page.url(),
    districtHeadingVisible: (await page.getByText(/District Overview/i).count()) > 0,
    loginHeadingVisible: (await page.getByText(/Login/i).count()) > 0,
    finalDemand: await stat(page, 'Total Final Demand'),
    allocated: await stat(page, 'Allocated Resources'),
    unmet: await stat(page, 'Unmet Demand'),
    coverage: await stat(page, 'Coverage %'),
    inventoryRows: await inventoryRows(page),
    allocationRows: await page.locator('table tbody tr').count(),
    errorBanner: ((await page.locator('div.text-red-700').count()) > 0 ? (((await page.locator('div.text-red-700').first().textContent()) || '').trim()) : ''),
  }

  const endpointProbe = [
    await probe(api, token, '/district/allocations'),
    await probe(api, token, '/district/unmet'),
    await probe(api, token, '/district/requests?latest_only=true'),
    await probe(api, token, '/district/demand-mode'),
    await probe(api, token, '/district/solver-status'),
    await probe(api, token, '/metadata/resources'),
    await probe(api, token, '/district/kpis'),
    await probe(api, token, '/district/stock'),
    await probe(api, token, '/district/claims'),
    await probe(api, token, '/district/consumptions'),
    await probe(api, token, '/district/returns'),
  ]

  const kpi = await api.get('http://127.0.0.1:8000/district/kpis', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })
  const stock = await api.get('http://127.0.0.1:8000/district/stock', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })

  await page.screenshot({ path: `${OUT_DIR}/district-before-after.png`, fullPage: true })

  await savePartial('district', {
    requestStatus,
    runStatus,
    before,
    after,
    api: {
      kpiStatus: kpi.status(),
      kpiBody: kpi.ok() ? await kpi.json() : null,
      stockStatus: stock.status(),
      stockRows: stock.ok() ? (await stock.json()).length : 0,
      endpointProbe,
    },
  })

  await api.dispose()
})

test('state cross-role observation', async ({ page }) => {
  test.setTimeout(90000)
  try {
    await loginUi(page, creds.state)
  } catch {
    await savePartial('state', {
      loginStatus: 'ui_login_failed',
      note: 'State UI login with provided credentials did not navigate to /state in this run',
    })
    return
  }
  await settleDashboard(page, 6000)
  const { api, token } = await loginApi(creds.state.username, creds.state.password)

  const kpi = await api.get('http://127.0.0.1:8000/state/kpis', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })
  const stock = await api.get('http://127.0.0.1:8000/state/stock', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })

  await page.screenshot({ path: `${OUT_DIR}/state-overview.png`, fullPage: true })

  await savePartial('state', {
    stats: {
      totalDemand: await stat(page, 'Total District Demand'),
      totalAllocated: await stat(page, 'Total Allocated to Districts'),
      totalUnmet: await stat(page, 'Total Unmet'),
      inventoryRows: await inventoryRows(page),
    },
    api: {
      kpiStatus: kpi.status(),
      kpiBody: kpi.ok() ? await kpi.json() : null,
      stockStatus: stock.status(),
      stockRows: stock.ok() ? (await stock.json()).length : 0,
    },
  })

  await api.dispose()
})

test('national cross-role observation', async ({ page }) => {
  test.setTimeout(90000)
  await loginUi(page, creds.national)
  await settleDashboard(page, 35000)
  const { api, token } = await loginApi(creds.national.username, creds.national.password)

  const kpi = await api.get('http://127.0.0.1:8000/national/kpis', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })
  const stock = await api.get('http://127.0.0.1:8000/national/stock', { headers: { Authorization: `Bearer ${token}` }, timeout: 10000 })

  await page.screenshot({ path: `${OUT_DIR}/national-overview.png`, fullPage: true })

  await savePartial('national', {
    stats: {
      nationalDemand: await stat(page, 'National Demand'),
      nationalStock: await stat(page, 'National Stock'),
      totalUnmet: await stat(page, 'Total Unmet'),
      inventoryRows: await inventoryRows(page),
    },
    api: {
      kpiStatus: kpi.status(),
      kpiBody: kpi.ok() ? await kpi.json() : null,
      stockStatus: stock.status(),
      stockRows: stock.ok() ? (await stock.json()).length : 0,
    },
  })

  await api.dispose()
})
