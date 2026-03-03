import { expect, test } from '@playwright/test'
import { mkdir, writeFile } from 'fs/promises'

import { loginAs } from './helpers'

type DelaySample = {
  step: string
  delayMs: number
}

async function measureVisibleDelay(
  step: string,
  action: () => Promise<void>,
  assertion: () => Promise<void>,
): Promise<DelaySample> {
  const started = Date.now()
  await action()
  await assertion()
  const ended = Date.now()
  return { step, delayMs: Math.max(0, ended - started) }
}

test('frontend render delay profile', async ({ page }) => {
  const samples: DelaySample[] = []

  await page.goto('/login')
  const loginDelay = await measureVisibleDelay(
    'login_to_district_overview',
    async () => {
      await loginAs(page, 'district', 'district_603', 'district123')
    },
    async () => {
      await expect(page.getByText(/District Overview/i)).toBeVisible()
    },
  )
  samples.push(loginDelay)

  samples.push(
    await measureVisibleDelay(
      'district_overview_to_request_page',
      async () => {
        await page.goto('/district/request')
      },
      async () => {
        await expect(page.getByText(/District Resource Request/i)).toBeVisible()
      },
    ),
  )

  samples.push(
    await measureVisibleDelay(
      'request_page_to_district_overview',
      async () => {
        await page.goto('/district')
      },
      async () => {
        await expect(page.getByText(/District Overview/i)).toBeVisible()
      },
    ),
  )

  const averageDelayMs = samples.length > 0
    ? Number((samples.reduce((acc, s) => acc + s.delayMs, 0) / samples.length).toFixed(2))
    : 0

  const report = {
    generatedAt: new Date().toISOString(),
    sampleCount: samples.length,
    averageDelayMs,
    samples,
  }

  await mkdir('test-results', { recursive: true })
  await writeFile('test-results/render-delay-report.json', JSON.stringify(report, null, 2), 'utf-8')

  expect(samples.length).toBeGreaterThan(0)
})
