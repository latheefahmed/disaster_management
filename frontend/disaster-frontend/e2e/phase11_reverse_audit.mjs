import { chromium, request as playwrightRequest } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:5174'
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

const users = {
  district: { username: 'district_603', password: 'district123', role: 'district' },
  state: { username: 'state_33', password: 'state123', role: 'state' },
  national: { username: 'national_admin', password: 'national123', role: 'national' },
  admin: { username: 'admin', password: 'admin123', role: 'admin' },
}

const OUT_DIR = 'test-results/phase11-reverse-audit'

async function loginApi(apiContext, { username, password }) {
  const res = await apiContext.post(`${BACKEND_URL}/auth/login`, { data: { username, password } })
  if (!res.ok()) throw new Error(`API login failed for ${username}: ${res.status()}`)
  const body = await res.json()
  return body.access_token
}

async function uiLogin(page, { username, password, role }) {
  await page.goto(`${FRONTEND_URL}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder(/Username/i).fill(username)
  await page.getByPlaceholder(/Password/i).fill(password)
  await page.locator('select').first().selectOption(role)
  await page.getByRole('button', { name: 'Login' }).click()
  await page.waitForURL(new RegExp(`/${role}$`), { timeout: 20000 })
}

async function readStatCard(page, label) {
  const card = page.locator('div.rounded-xl.border.bg-white.p-4.shadow-sm').filter({ has: page.getByText(label, { exact: true }) }).first()
  if (await card.count() === 0) return null
  const valueText = (await card.locator('p.text-xl.font-semibold').first().textContent()) || ''
  const numeric = Number(String(valueText).replace(/[^0-9.-]/g, ''))
  return { raw: valueText.trim(), numeric: Number.isFinite(numeric) ? numeric : null }
}

async function countTableRows(page) {
  const tables = page.locator('table')
  const tCount = await tables.count()
  let totalRows = 0
  for (let i = 0; i < tCount; i++) {
    totalRows += await tables.nth(i).locator('tbody tr').count()
  }
  return totalRows
}

async function countInventoryRows(page) {
  const inventoryHeader = page.getByText('Resource Inventory', { exact: true })
  if ((await inventoryHeader.count()) === 0) return 0
  return await page.locator('button').filter({ hasText: /Total:/ }).count()
}

async function observeDistrict(page, token) {
  const before = {
    finalDemand: await readStatCard(page, 'Total Final Demand'),
    allocated: await readStatCard(page, 'Allocated Resources'),
    unmet: await readStatCard(page, 'Unmet Demand'),
    coverage: await readStatCard(page, 'Coverage %'),
    allocationRows: await countTableRows(page),
    inventoryRows: await countInventoryRows(page),
  }

  await page.screenshot({ path: `${OUT_DIR}/district-before.png`, fullPage: true })

  const requestBody = {
    resource_id: 'water',
    time: 1,
    quantity: 25,
    priority: 1,
    urgency: 1,
    confidence: 1.0,
    source: 'human',
  }

  const createReq = await page.request.post(`${BACKEND_URL}/district/request`, {
    headers: { Authorization: `Bearer ${token}` },
    data: requestBody,
  })

  const runRes = await page.request.post(`${BACKEND_URL}/district/run`, {
    headers: { Authorization: `Bearer ${token}` },
  })

  await page.waitForTimeout(2500)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)

  const after = {
    finalDemand: await readStatCard(page, 'Total Final Demand'),
    allocated: await readStatCard(page, 'Allocated Resources'),
    unmet: await readStatCard(page, 'Unmet Demand'),
    coverage: await readStatCard(page, 'Coverage %'),
    allocationRows: await countTableRows(page),
    inventoryRows: await countInventoryRows(page),
  }

  await page.screenshot({ path: `${OUT_DIR}/district-after.png`, fullPage: true })

  const kpiApi = await page.request.get(`${BACKEND_URL}/district/kpis`, { headers: { Authorization: `Bearer ${token}` } })
  const stockApi = await page.request.get(`${BACKEND_URL}/district/stock`, { headers: { Authorization: `Bearer ${token}` } })

  return {
    requestStatus: createReq.status(),
    runStatus: runRes.status(),
    before,
    after,
    api: {
      kpiStatus: kpiApi.status(),
      kpiBody: kpiApi.ok() ? await kpiApi.json() : null,
      stockStatus: stockApi.status(),
      stockCount: stockApi.ok() ? (await stockApi.json()).length : 0,
    },
  }
}

async function observeRole(page, role, token) {
  const snapshot = {}

  if (role === 'state') {
    snapshot.totalDemand = await readStatCard(page, 'Total District Demand')
    snapshot.totalAllocated = await readStatCard(page, 'Total Allocated to Districts')
    snapshot.totalUnmet = await readStatCard(page, 'Total Unmet')
    snapshot.inventoryRows = await countInventoryRows(page)
    await page.screenshot({ path: `${OUT_DIR}/state-overview.png`, fullPage: true })

    const kpiApi = await page.request.get(`${BACKEND_URL}/state/kpis`, { headers: { Authorization: `Bearer ${token}` } })
    const stockApi = await page.request.get(`${BACKEND_URL}/state/stock`, { headers: { Authorization: `Bearer ${token}` } })
    snapshot.api = {
      kpiStatus: kpiApi.status(),
      kpiBody: kpiApi.ok() ? await kpiApi.json() : null,
      stockStatus: stockApi.status(),
      stockCount: stockApi.ok() ? (await stockApi.json()).length : 0,
    }
  }

  if (role === 'national') {
    snapshot.nationalDemand = await readStatCard(page, 'National Demand')
    snapshot.nationalStock = await readStatCard(page, 'National Stock')
    snapshot.totalUnmet = await readStatCard(page, 'Total Unmet')
    snapshot.inventoryRows = await countInventoryRows(page)
    await page.screenshot({ path: `${OUT_DIR}/national-overview.png`, fullPage: true })

    const kpiApi = await page.request.get(`${BACKEND_URL}/national/kpis`, { headers: { Authorization: `Bearer ${token}` } })
    const stockApi = await page.request.get(`${BACKEND_URL}/national/stock`, { headers: { Authorization: `Bearer ${token}` } })
    snapshot.api = {
      kpiStatus: kpiApi.status(),
      kpiBody: kpiApi.ok() ? await kpiApi.json() : null,
      stockStatus: stockApi.status(),
      stockCount: stockApi.ok() ? (await stockApi.json()).length : 0,
    }
  }

  return snapshot
}

async function run() {
  await mkdir(OUT_DIR, { recursive: true })

  const apiContext = await playwrightRequest.newContext()
  const tokens = {
    district: await loginApi(apiContext, users.district),
    state: await loginApi(apiContext, users.state),
    national: await loginApi(apiContext, users.national),
    admin: await loginApi(apiContext, users.admin),
  }

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()

  const result = {
    frontendUrl: FRONTEND_URL,
    backendUrl: BACKEND_URL,
    timestamp: new Date().toISOString(),
    district: null,
    state: null,
    national: null,
  }

  await uiLogin(page, users.district)
  result.district = await observeDistrict(page, tokens.district)

  await uiLogin(page, users.state)
  result.state = await observeRole(page, 'state', tokens.state)

  await uiLogin(page, users.national)
  result.national = await observeRole(page, 'national', tokens.national)

  await browser.close()
  await apiContext.dispose()

  await writeFile(`${OUT_DIR}/observations.json`, JSON.stringify(result, null, 2), 'utf-8')
  console.log(JSON.stringify(result, null, 2))
}

run().catch(async (err) => {
  console.error(err)
  process.exit(1)
})
