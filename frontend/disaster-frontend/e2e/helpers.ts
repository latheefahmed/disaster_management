import { expect, Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

export async function loginAs(page: Page, role: 'district' | 'state' | 'national' | 'admin', username: string, password = 'pw') {
  await page.goto('/login')
  await page.getByPlaceholder(/Username/i).fill(username)
  await page.getByPlaceholder(/Password/i).fill(password)
  await page.locator('select').first().selectOption(role)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(new RegExp(`/${role}$`))
}

export async function saveEvidence(page: Page, name: string) {
  await page.screenshot({ path: `test-results/${name}.png`, fullPage: true })
}

type ConsoleEvent = {
  type: string
  text: string
  location?: {
    url: string
    lineNumber: number
    columnNumber: number
  }
}

type NetworkEvent = {
  kind: 'response' | 'requestfailed'
  method: string
  url: string
  status?: number
  statusText?: string
  failureText?: string
}

export function attachTelemetry(page: Page, name: string) {
  const consoleEvents: ConsoleEvent[] = []
  const networkEvents: NetworkEvent[] = []

  const onConsole = (msg: any) => {
    const loc = msg.location?.()
    consoleEvents.push({
      type: String(msg.type?.() ?? 'log'),
      text: String(msg.text?.() ?? ''),
      location: loc
        ? {
            url: String(loc.url ?? ''),
            lineNumber: Number(loc.lineNumber ?? 0),
            columnNumber: Number(loc.columnNumber ?? 0),
          }
        : undefined,
    })
  }

  const onResponse = (response: any) => {
    const req = response.request?.()
    networkEvents.push({
      kind: 'response',
      method: String(req?.method?.() ?? 'GET'),
      url: String(response.url?.() ?? ''),
      status: Number(response.status?.() ?? 0),
      statusText: String(response.statusText?.() ?? ''),
    })
  }

  const onRequestFailed = (request: any) => {
    networkEvents.push({
      kind: 'requestfailed',
      method: String(request.method?.() ?? 'GET'),
      url: String(request.url?.() ?? ''),
      failureText: String(request.failure?.()?.errorText ?? 'unknown'),
    })
  }

  page.on('console', onConsole)
  page.on('response', onResponse)
  page.on('requestfailed', onRequestFailed)

  return {
    async flush() {
      const path = `test-results/${name}.telemetry.json`
      await mkdir(dirname(path), { recursive: true })
      await writeFile(
        path,
        JSON.stringify(
          {
            test: name,
            captured_at: new Date().toISOString(),
            console: consoleEvents,
            network: networkEvents,
            http_errors: networkEvents.filter(e => e.kind === 'response' && typeof e.status === 'number' && e.status >= 400),
            request_failures: networkEvents.filter(e => e.kind === 'requestfailed'),
          },
          null,
          2,
        ),
        'utf-8',
      )
      page.off('console', onConsole)
      page.off('response', onResponse)
      page.off('requestfailed', onRequestFailed)
    },
    assertNoHttpErrors() {
      const httpErrors = networkEvents.filter(
        e => e.kind === 'response' && typeof e.status === 'number' && e.status >= 400,
      )
      const requestFailures = networkEvents.filter(e => e.kind === 'requestfailed')
      expect(httpErrors, `${name} has HTTP 4xx/5xx responses`).toEqual([])
      expect(requestFailures, `${name} has failed network requests`).toEqual([])
    },
  }
}
