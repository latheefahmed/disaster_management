import { chromium, request as playwrightRequest } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const BACKEND_URL = 'http://127.0.0.1:8000'
const FRONTEND_CANDIDATES = [
  'http://localhost:5173',
  'http://localhost:5174',
  'http://localhost:5175',
  'http://localhost:5176',
  'http://127.0.0.1:5173',
  'http://127.0.0.1:5174',
  'http://127.0.0.1:5175',
  'http://127.0.0.1:5176',
]

const CREDS = {
  district: { username: 'district_603', password: 'district123', role: 'district' },
  state: { username: 'state_33', password: 'state123', role: 'state' },
  national: { username: 'national_admin', password: 'national123', role: 'national' },
  admin: { username: 'admin', password: 'admin123', role: 'admin' },
}

const OUT_DIR = 'test-results/phase11-root-cause-audit'

async function detectFrontendUrl() {
  if (process.env.FRONTEND_URL) return process.env.FRONTEND_URL
  for (const base of FRONTEND_CANDIDATES) {
    try {
      const res = await fetch(`${base}/login`, { method: 'GET' })
      if (res.ok()) return base
    } catch {}
  }
  return 'http://localhost:5173'
}

function asNumber(v) {
  const n = Number(String(v ?? '').replace(/[^0-9.-]/g, ''))
  return Number.isFinite(n) ? n : null
}

function shortJson(v, limit = 1000) {
  const s = JSON.stringify(v, null, 2)
  if (s.length <= limit) return s
  return `${s.slice(0, limit)}\n... [truncated]`
}

async function screenshot(page, name) {
  await page.screenshot({ path: `${OUT_DIR}/${name}.png`, fullPage: true })
}

async function uiLogin(page, frontendUrl, cred) {
  await page.goto(`${frontendUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder(/Username/i).fill(cred.username)
  await page.getByPlaceholder(/Password/i).fill(cred.password)
  await page.locator('select').first().selectOption(cred.role)
  await page.getByRole('button', { name: 'Login' }).click()
  await page.waitForURL(new RegExp(`/${cred.role}$`), { timeout: 25000 })
}

async function apiLogin(api, cred) {
  let lastStatus = 'unknown'
  for (let attempt = 1; attempt <= 5; attempt++) {
    const res = await api.post(`${BACKEND_URL}/auth/login`, {
      data: { username: cred.username, password: cred.password },
      failOnStatusCode: false,
      timeout: 12000,
    })
    lastStatus = String(res.status())
    if (res.ok()) {
      const body = await res.json()
      return body.access_token
    }
    await new Promise((resolve) => setTimeout(resolve, attempt * 500))
  }
  throw new Error(`API login failed for ${cred.username}: ${lastStatus}`)
}

async function statCardValue(page, label) {
  const card = page.locator('div.rounded-xl.border.bg-white.p-4.shadow-sm').filter({ has: page.getByText(label, { exact: true }) }).first()
  if ((await card.count()) === 0) return null
  const txt = ((await card.locator('p.text-xl.font-semibold').first().textContent()) || '').trim()
  return { raw: txt, numeric: asNumber(txt) }
}

async function parseInventoryPanel(page) {
  const rows = []
  const buttons = page.locator('button').filter({ hasText: /Total:/ })
  const n = await buttons.count()
  for (let i = 0; i < n; i++) {
    const text = ((await buttons.nth(i).textContent()) || '').replace(/\s+/g, ' ').trim()
    const m = text.match(/^(.*?)\s+Total:\s*([0-9.,-]+)/i)
    if (m) {
      rows.push({ resource_id: m[1].trim(), quantity: Number(m[2].replace(/,/g, '')) })
    } else {
      rows.push({ raw: text })
    }
  }
  return rows
}

async function collectCanonicalResources(page, frontendUrl) {
  await page.goto(`${frontendUrl}/district/request`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const select = page.locator('label', { hasText: 'Resource' }).first().locator('xpath=following-sibling::select').first()
  const options = await select.locator('option').allTextContents()
  const cleaned = options
    .map(o => o.replace(/\s+/g, ' ').trim())
    .filter(o => o && !/^select resource$/i.test(o))
  const canonical = cleaned.map(o => {
    const left = o.split('—')[0]?.trim() || o
    return left
  })
  await screenshot(page, 'step1_district_request_dropdown')
  return { optionText: cleaned, canonicalResourceIds: Array.from(new Set(canonical)) }
}

async function collectDistrictStockNetworkOnRefresh(page, frontendUrl) {
  const hits = []
  const handler = async (res) => {
    const url = res.url()
    if (!url.includes('/district/stock')) return
    let body = null
    try { body = await res.json() } catch {}
    hits.push({ url, status: res.status(), body })
  }
  page.on('response', handler)
  await page.goto(`${frontendUrl}/district`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3500)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4500)
  page.off('response', handler)
  await screenshot(page, 'step3_district_overview_after_refresh')

  const last = [...hits].reverse().find(h => Array.isArray(h.body)) || hits[hits.length - 1] || null
  const rows = Array.isArray(last?.body) ? last.body : []
  return {
    hitCount: hits.length,
    lastHitStatus: last?.status ?? null,
    rowCount: rows.length,
    resource_ids: rows.map(r => r.resource_id),
    quantity_fields: rows.map(r => ({
      resource_id: r.resource_id,
      district_stock: r.district_stock,
      state_stock: r.state_stock,
      national_stock: r.national_stock,
    })),
    raw_last_body: rows,
  }
}

async function step4QuantitySemantics(page) {
  await page.goto(page.url().replace(/\/district\/request$/, '/district').replace(/\/login$/, '/district'), { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)

  const inventoryRows = await parseInventoryPanel(page)
  const waterInventory = inventoryRows.find(r => String(r.resource_id || '').toLowerCase().includes('water'))?.quantity ?? null
  const kpiAllocated = (await statCardValue(page, 'Allocated Resources'))?.numeric ?? null

  await page.getByRole('button', { name: 'Allocations' }).click()
  await page.waitForTimeout(1500)

  const tableRows = page.locator('table tbody tr')
  const n = await tableRows.count()
  let sumAllocatedWater = 0
  for (let i = 0; i < n; i++) {
    const cells = tableRows.nth(i).locator('td')
    const c = await cells.count()
    if (c < 2) continue
    const resource = ((await cells.nth(0).textContent()) || '').toLowerCase()
    const allocated = asNumber(await cells.nth(1).textContent()) || 0
    if (resource.includes('water')) sumAllocatedWater += allocated
  }

  let inferred = 'unknown'
  if (waterInventory != null && sumAllocatedWater > 0 && Math.abs(waterInventory - sumAllocatedWater) < 1e-6) {
    inferred = 'allocated'
  } else if (waterInventory != null && kpiAllocated != null && Math.abs(waterInventory - kpiAllocated) < 1e-6) {
    inferred = 'allocated'
  } else if (waterInventory != null && sumAllocatedWater >= 0 && waterInventory >= sumAllocatedWater) {
    inferred = 'available stock'
  }

  await screenshot(page, 'step4_allocations_tab')
  return {
    inventory_water_quantity: waterInventory,
    sum_allocated_water_ui_rows: sumAllocatedWater,
    district_kpi_allocated_value: kpiAllocated,
    inferred_semantics: inferred,
  }
}

async function step5And6ClaimRepro(page, api, districtToken) {
  await page.goto(page.url().includes('/district') ? page.url() : page.url().replace(/\/login$/, '/district'), { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: 'Allocations' }).click()
  await page.waitForTimeout(1500)

  const claimsBeforeRes = await api.get(`${BACKEND_URL}/district/claims`, { headers: { Authorization: `Bearer ${districtToken}` } })
  const claimsBefore = claimsBeforeRes.ok() ? await claimsBeforeRes.json() : []

  const firstRow = page.locator('table tbody tr').filter({ has: page.getByRole('button', { name: 'Claim' }) }).first()
  const cells = firstRow.locator('td')
  const firstResource = ((await cells.nth(0).textContent()) || '').trim()
  const firstAllocated = asNumber(await cells.nth(1).textContent())

  let claimRequestPayload = null
  let claimResponsePayload = null
  let claimStatus = null

  const onReq = (req) => {
    if (req.method() === 'POST' && req.url().includes('/district/claim')) {
      try { claimRequestPayload = req.postDataJSON() } catch { claimRequestPayload = req.postData() }
    }
  }
  const onRes = async (res) => {
    if (res.request().method() === 'POST' && res.url().includes('/district/claim')) {
      claimStatus = res.status()
      try { claimResponsePayload = await res.json() } catch { try { claimResponsePayload = await res.text() } catch {} }
    }
  }

  page.on('request', onReq)
  page.on('response', onRes)

  const claimBtn = firstRow.getByRole('button', { name: 'Claim' })
  if (await claimBtn.count()) {
    await claimBtn.click()
    await page.waitForTimeout(2500)
  }

  page.off('request', onReq)
  page.off('response', onRes)

  const err = page.locator('div.text-red-700').first()
  const errorMessage = (await err.count()) ? (((await err.textContent()) || '').trim()) : ''

  let claimedBeforeForSelected = null
  if (claimRequestPayload && typeof claimRequestPayload === 'object') {
    const rb = claimsBefore.find(
      c => String(c.resource_id) === String(claimRequestPayload.resource_id)
        && Number(c.time) === Number(claimRequestPayload.time)
    )
    claimedBeforeForSelected = rb ? Number(rb.claimed_quantity || 0) : 0
  }

  const criticalExceededBug =
    /claim quantity exceeds allocated quantity/i.test(errorMessage)
    && Number(claimedBeforeForSelected || 0) === 0

  await screenshot(page, 'step5_claim_attempt')

  return {
    selected_allocation_row: {
      resource: firstResource,
      allocated_quantity: firstAllocated,
      claimed_quantity_if_visible: null,
    },
    claim_error_message: errorMessage || null,
    claim_http_status: claimStatus,
    critical_bug_flag: criticalExceededBug,
    district_claim_request_payload: claimRequestPayload,
    district_claim_response_payload: claimResponsePayload,
  }
}

async function roleInventoryAndStock(page, frontendUrl, api, cred, stockPath) {
  await uiLogin(page, frontendUrl, cred)
  await page.waitForTimeout(2500)
  const uiRows = await parseInventoryPanel(page)
  const token = await apiLogin(api, cred)
  const stockRes = await api.get(`${BACKEND_URL}${stockPath}`, { headers: { Authorization: `Bearer ${token}` } })
  const stockBody = stockRes.ok() ? await stockRes.json() : null
  await screenshot(page, `step7_${cred.role}_overview`)
  return {
    ui_inventory_rows: uiRows,
    stock_status: stockRes.status(),
    stock_json: stockBody,
  }
}

function mapByResource(rows, key) {
  const m = new Map()
  for (const r of Array.isArray(rows) ? rows : []) {
    m.set(String(r.resource_id), Number(r[key] || 0))
  }
  return m
}

async function step8HugeQuantity(page, frontendUrl) {
  await page.goto(`${frontendUrl}/district/request`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)

  let reqPayload = null
  let reqResp = null
  let reqStatus = null

  const onReq = (req) => {
    if (req.method() === 'POST' && req.url().includes('/district/request-batch')) {
      try { reqPayload = req.postDataJSON() } catch { reqPayload = req.postData() }
    }
  }
  const onRes = async (res) => {
    if (res.request().method() === 'POST' && res.url().includes('/district/request-batch')) {
      reqStatus = res.status()
      try { reqResp = await res.json() } catch { try { reqResp = await res.text() } catch {} }
    }
  }

  page.on('request', onReq)
  page.on('response', onRes)

  const resourceSelect = page.locator('label', { hasText: 'Resource' }).first().locator('xpath=following-sibling::select').first()
  const options = await resourceSelect.locator('option').allTextContents()
  const foodOption = options.find(o => /food[_\s-]?packets/i.test(o))

  let accepted = false
  let validationContext = 'food_packets option not present in resource dropdown'

  if (foodOption) {
    const chosenId = foodOption.split('—')[0].trim()
    await resourceSelect.selectOption(chosenId)
    await page.locator('label', { hasText: 'Quantity' }).first().locator('xpath=following-sibling::input').first().fill('999999999')

    await page.getByRole('button', { name: 'Add to Request Batch' }).click()
    await page.waitForTimeout(700)
    const pendingResponse = page.waitForResponse(
      (res) => res.request().method() === 'POST' && res.url().includes('/district/request-batch'),
      { timeout: 12000 },
    ).catch(() => null)
    await page.getByRole('button', { name: /Submit All Requests|Submitting/ }).click()
    const responseEvent = await pendingResponse
    if (responseEvent) {
      reqStatus = responseEvent.status()
      try { reqResp = await responseEvent.json() } catch { try { reqResp = await responseEvent.text() } catch {} }
    }
    await page.waitForTimeout(1800)

    const success = page.locator('div.text-green-600').first()
    const error = page.locator('div.text-red-600').first()
    const successText = (await success.count()) ? (((await success.textContent()) || '').trim()) : ''
    const errorText = (await error.count()) ? (((await error.textContent()) || '').trim()) : ''

    accepted = Boolean((reqStatus && reqStatus >= 200 && reqStatus < 300) || /submitted/i.test(successText))
    validationContext = successText || errorText || `selected option: ${chosenId}`
  }

  page.off('request', onReq)
  page.off('response', onRes)

  await screenshot(page, 'step8_huge_quantity_validation')

  return {
    requested_resource: 'food_packets',
    quantity_attempted: 999999999,
    accepted,
    status: reqStatus,
    response: reqResp,
    request_payload: reqPayload,
    evidence_message: validationContext,
    critical_validation_bug: accepted,
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true })
  const frontendUrl = await detectFrontendUrl()

  const api = await playwrightRequest.newContext()
  const districtToken = await apiLogin(api, CREDS.district)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()

  const evidence = {
    timestamp: new Date().toISOString(),
    frontendUrl,
    backendUrl: BACKEND_URL,
  }

  try {
    await uiLogin(page, frontendUrl, CREDS.district)

    const step1 = await collectCanonicalResources(page, frontendUrl)
    const step2 = {
      district_inventory_resources: await (async () => {
        await page.goto(`${frontendUrl}/district`, { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(2500)
        await screenshot(page, 'step2_district_inventory_panel')
        return await parseInventoryPanel(page)
      })(),
    }

    const step3 = await collectDistrictStockNetworkOnRefresh(page, frontendUrl)
    const step4 = await step4QuantitySemantics(page)
    const step5_6 = await step5And6ClaimRepro(page, api, districtToken)

    const districtStockMap = mapByResource(step3.raw_last_body, 'district_stock')
    const stateCross = await roleInventoryAndStock(page, frontendUrl, api, CREDS.state, '/state/stock')
    const nationalCross = await roleInventoryAndStock(page, frontendUrl, api, CREDS.national, '/national/stock')

    const stateStockMap = mapByResource(stateCross.stock_json, 'state_stock')
    const nationalStockMap = mapByResource(nationalCross.stock_json, 'national_stock')

    const resources = new Set([...districtStockMap.keys(), ...stateStockMap.keys(), ...nationalStockMap.keys()])
    const hierarchy = []
    const hierarchyViolations = []
    for (const r of resources) {
      const d = districtStockMap.get(r)
      const s = stateStockMap.get(r)
      const n = nationalStockMap.get(r)
      const row = { resource_id: r, district_stock: d, state_stock: s, national_stock: n }
      hierarchy.push(row)
      if (d != null && s != null && n != null && !(d <= s && s <= n)) hierarchyViolations.push(row)
    }

    await uiLogin(page, frontendUrl, CREDS.district)
    const step8 = await step8HugeQuantity(page, frontendUrl)

    const canonicalSet = new Set(step1.canonicalResourceIds.map(r => String(r).trim().toLowerCase()))
    const inventorySet = new Set(step2.district_inventory_resources.map(r => String(r.resource_id || '').trim().toLowerCase()))
    const missingResources = Array.from(canonicalSet).filter(r => r && !inventorySet.has(r))

    const severity = []
    if (missingResources.length) severity.push({ level: 'High', issue: 'Inventory panel missing canonical resources', evidence: missingResources })
    if (step3.rowCount <= 1) severity.push({ level: 'High', issue: '/district/stock returns one or fewer rows', evidence: { rowCount: step3.rowCount, resource_ids: step3.resource_ids } })
    if (step5_6.critical_bug_flag) severity.push({ level: 'Critical', issue: 'Claim rejected as exceeding allocation despite zero prior claimed quantity', evidence: { error: step5_6.claim_error_message, request: step5_6.district_claim_request_payload } })
    if (hierarchyViolations.length) severity.push({ level: 'Medium', issue: 'Stock hierarchy violation district<=state<=national', evidence: hierarchyViolations })
    if (step8.critical_validation_bug) severity.push({ level: 'Critical', issue: 'Huge quantity accepted in district request', evidence: { payload: step8.request_payload, status: step8.status } })

    const finalVerdict = severity.some(s => s.level === 'Critical')
      ? 'FAIL'
      : severity.length > 0
        ? 'PARTIAL'
        : 'PASS'

    const reportMd = `# PHASE-11 ROOT CAUSE AUDIT REPORT\n\nA. Canonical Resources\n- ${step1.canonicalResourceIds.length ? step1.canonicalResourceIds.join(', ') : '(none detected)'}\n\nB. Inventory Panel Resources\n- ${step2.district_inventory_resources.length ? step2.district_inventory_resources.map(r => `${r.resource_id}: ${r.quantity ?? 'n/a'}`).join('; ') : '(none shown)'}\n\nC. Missing Resources\n- ${missingResources.length ? missingResources.join(', ') : 'None'}\n\nD. /district/stock API Rows (json excerpt)\n\n\`\`\`json\n${shortJson({ rowCount: step3.rowCount, resource_ids: step3.resource_ids, quantity_fields: step3.quantity_fields }, 2200)}\n\`\`\`\n\nE. Inventory Quantity Semantics\n- inventory_water_quantity: ${step4.inventory_water_quantity}\n- sum_allocated_water_ui_rows: ${step4.sum_allocated_water_ui_rows}\n- district_kpi_allocated_value: ${step4.district_kpi_allocated_value}\n- inferred: ${step4.inferred_semantics}\n\nF. Claim Failure\n- selected resource: ${step5_6.selected_allocation_row.resource}\n- allocated_quantity: ${step5_6.selected_allocation_row.allocated_quantity}\n- claimed_quantity (if visible): ${step5_6.selected_allocation_row.claimed_quantity_if_visible ?? 'not visible in row'}\n- error message: ${step5_6.claim_error_message ?? 'none observed'}\n- http status: ${step5_6.claim_http_status ?? 'not captured'}\n\nG. /district/claim Payload (json excerpt)\n\n\`\`\`json\n${shortJson({ request: step5_6.district_claim_request_payload, response: step5_6.district_claim_response_payload }, 2200)}\n\`\`\`\n\nH. Cross Role Inventory Comparison\n\n| resource_id | district_stock | state_stock | national_stock |\n|---|---:|---:|---:|\n${hierarchy.map(r => `| ${r.resource_id} | ${r.district_stock ?? 'n/a'} | ${r.state_stock ?? 'n/a'} | ${r.national_stock ?? 'n/a'} |`).join('\n')}\n\n- hierarchy violations: ${hierarchyViolations.length}\n\nI. Validation Bugs\n- huge quantity test (food_packets=999999999) accepted: ${step8.accepted ? 'YES' : 'NO'}\n- status: ${step8.status ?? 'not captured'}\n- evidence: ${step8.evidence_message}\n\nJ. Severity Ranking\n${severity.length ? severity.map((s, i) => `${i + 1}. [${s.level}] ${s.issue}`).join('\n') : 'No defects observed in this run.'}\n\nK. Final Verdict\n- ${finalVerdict}\n\n` 

    evidence.step1 = step1
    evidence.step2 = step2
    evidence.step3 = step3
    evidence.step4 = step4
    evidence.step5_6 = step5_6
    evidence.step7 = {
      state: stateCross,
      national: nationalCross,
      hierarchy,
      hierarchyViolations,
    }
    evidence.step8 = step8
    evidence.missingResources = missingResources
    evidence.severity = severity
    evidence.finalVerdict = finalVerdict

    await writeFile(`${OUT_DIR}/evidence.json`, JSON.stringify(evidence, null, 2), 'utf-8')
    const reportPath = path.resolve(process.cwd(), '..', '..', 'backend', 'PHASE11_ROOT_CAUSE_AUDIT_REPORT.md')
    await writeFile(reportPath, reportMd, 'utf-8')

    console.log(JSON.stringify({
      frontendUrl,
      evidencePath: `${OUT_DIR}/evidence.json`,
      reportPath,
      finalVerdict,
      severityCount: severity.length,
    }, null, 2))
  } finally {
    await browser.close()
    await api.dispose()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
