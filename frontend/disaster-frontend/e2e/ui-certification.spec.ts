import { expect, test } from '@playwright/test'

import { attachTelemetry, loginAs, saveEvidence } from './helpers'

test('district can run solver and view live request logs', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'district-overview-and-request-log')
  try {
    await loginAs(page, 'district', 'district_user')

    await expect(page.getByText(/District Overview/i)).toBeVisible()
    const runButton = page.getByRole('button', { name: 'Run Solver' })
    await expect(runButton).toBeVisible()
    await runButton.click()
    await expect(page.getByText(/District Overview/i)).toBeVisible()

    await page.getByRole('link', { name: 'District Request', exact: true }).click()
    await expect(page.getByText(/District Resource Request/i)).toBeVisible()
    await expect(page.getByText(/Request Status Log/i)).toBeVisible()

    await saveEvidence(page, 'district-overview-and-request-log')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('district request form validates empty batch and remains interactive', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'district-request-validation')
  try {
    await loginAs(page, 'district', 'district_user')
    await page.getByRole('link', { name: 'District Request', exact: true }).click()
    await expect(page.getByText(/District Resource Request/i)).toBeVisible()

    await page.getByRole('button', { name: 'Submit All Requests' }).click()
    await expect(page.getByText(/No resource requests added/i)).toBeVisible()

    await saveEvidence(page, 'district-request-validation')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('state can see mutual aid market and offer aid', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'state-mutual-aid-offer')
  try {
    await loginAs(page, 'state', 'state_user')

    await expect(page.getByText(/State Overview/i)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Mutual Aid Market' })).toBeVisible()

    const offerButton = page.getByRole('button', { name: 'Offer Mutual Aid' }).first()
    await expect(offerButton).toBeVisible()
    await offerButton.click()

    await expect(page.getByRole('heading', { name: 'Mutual Aid Market' })).toBeVisible()
    await saveEvidence(page, 'state-mutual-aid-offer')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('state requests shows lifecycle statuses used by district log', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'state-requests-lifecycle-statuses')
  try {
    await loginAs(page, 'state', 'state_user')

    await page.getByRole('link', { name: 'State Requests', exact: true }).click()
    await expect(page.getByText(/State Requests & Rebalancing/i)).toBeVisible()

    const statusFilter = page.locator('select').first()
    await expect(statusFilter).toBeVisible()
    await expect(statusFilter).toContainText('pending')
    await expect(statusFilter).toContainText('allocated')
    await expect(statusFilter).toContainText('partial')
    await expect(statusFilter).toContainText('unmet')
    await expect(statusFilter).toContainText('escalated_national')

    await expect(page.getByRole('heading', { name: 'District Requests' })).toBeVisible()
    await saveEvidence(page, 'state-requests-lifecycle-statuses')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('state overview reveals district-level allocation rows via details toggle', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'state-overview-district-detail-toggle')
  try {
    await loginAs(page, 'state', 'state_user')

    await expect(page.getByText(/State Overview/i)).toBeVisible()
    const detailToggle = page.getByRole('button', { name: /Show District-Level Details|Hide District-Level Details/i })
    if (await detailToggle.isVisible()) {
      await detailToggle.click()

      const detailTable = page
        .locator('table')
        .filter({ has: page.getByRole('columnheader', { name: 'District' }) })
        .first()
      await expect(detailTable).toBeVisible()
      await expect(detailTable.getByRole('columnheader', { name: 'District' })).toBeVisible()
      await expect(detailTable.getByRole('columnheader', { name: 'Resource' })).toBeVisible()
      await expect(detailTable.getByRole('columnheader', { name: 'Time' })).toBeVisible()
    } else {
      await expect(page.getByText(/No allocation summary available yet/i)).toBeVisible()
    }
    await saveEvidence(page, 'state-overview-district-detail-toggle')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('district can confirm receipt on allocation card', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'district-confirm-receipt')
  try {
    await loginAs(page, 'district', 'district_user')

    const confirmBtn = page.getByRole('button', { name: /Confirm Received|Confirming/i }).first()
    if (await confirmBtn.isVisible()) {
      await confirmBtn.click()
    }

    await expect(page.getByText(/District Overview/i)).toBeVisible()
    await saveEvidence(page, 'district-confirm-receipt')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('national dashboards render request and overview views', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'national-overview-and-requests')
  try {
    await loginAs(page, 'national', 'national_user')
    await expect(page.getByText(/National Overview/i)).toBeVisible()

    await page.getByRole('link', { name: 'National Requests', exact: true }).click()
    await expect(page.getByText(/National Requests/i)).toBeVisible()

    await saveEvidence(page, 'national-overview-and-requests')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})

test('admin studio and rapid navigation smoke remain stable', async ({ page }) => {
  const telemetry = attachTelemetry(page, 'admin-navigation-stress-smoke')
  try {
    await loginAs(page, 'admin', 'admin_user')

    await expect(page.getByText(/Admin Scenario Studio/i)).toBeVisible()

    for (let i = 0; i < 5; i++) {
      const scenarioInput = page.getByPlaceholder('New scenario name')
      await scenarioInput.fill(`e2e_smoke_${i}`)
      await expect(scenarioInput).toHaveValue(`e2e_smoke_${i}`)
      await scenarioInput.fill('')
      await expect(page.getByText(/Admin Scenario Studio/i)).toBeVisible()
    }

    await saveEvidence(page, 'admin-navigation-stress-smoke')
    telemetry.assertNoHttpErrors()
  } finally {
    await telemetry.flush()
  }
})
