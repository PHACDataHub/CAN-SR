import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const backend = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000/api'

type Fixture = {
  email: string
  password: string
  token: string
  srId: string
}

async function createFixture(request: APIRequestContext): Promise<Fixture> {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  const email = `pdf-browser-${suffix}@example.com`
  const password = 'PdfBrowserPass123'
  const register = await request.post(`${backend}/auth/register`, {
    data: { email, full_name: 'PDF Browser E2E', password, confirm_password: password },
  })
  expect(register.ok(), await register.text()).toBeTruthy()
  const login = await request.post(`${backend}/auth/login`, {
    data: { email, password },
  })
  expect(login.ok(), await login.text()).toBeTruthy()
  const token = (await login.json()).access_token as string
  const auth = { Authorization: `Bearer ${token}` }
  const create = await request.post(`${backend}/sr/create`, {
    headers: auth,
    multipart: {
      name: 'PDF browser E2E fixture',
      description: 'Temporary Playwright fixture',
      criteria_yaml:
        'l1:\n  questions: []\n  possible_answers: []\n  include: [title, abstract, doi]\nl2:\n  questions: []\n  possible_answers: []\n  include: [fulltext]\n',
    },
  })
  expect(create.ok(), await create.text()).toBeTruthy()
  const srId = (await create.json()).id as string
  const upload = await request.post(`${backend}/cite/${srId}/upload-citations`, {
    headers: auth,
    multipart: {
      file: {
        name: 'citations.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(
          'title,abstract,doi,human_l1_decision\nMissing PDF,Needs a PDF,,include\n',
        ),
      },
    },
  })
  expect(upload.ok(), await upload.text()).toBeTruthy()
  return { email, password, token, srId }
}

async function authenticate(page: Page, token: string): Promise<void> {
  await page.addInitScript((accessToken) => {
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('token_type', 'Bearer')
    localStorage.setItem('isLoggedIn', 'true')
  }, token)
}

test.describe('PDF linkage browser workflow', () => {
  let fixture: Fixture

  test.beforeEach(async ({ request, page }) => {
    fixture = await createFixture(request)
    await authenticate(page, fixture.token)
  })

  test.afterEach(async ({ request }) => {
    if (!fixture) return
    await request.delete(`${backend}/sr/${fixture.srId}/hard`, {
      headers: { Authorization: `Bearer ${fixture.token}` },
    })
  })

  test('launches, monitors, dismisses, and preserves manual fallback', async ({ page }) => {
    await page.goto(`/en/can-sr/l2-screen?sr_id=${encodeURIComponent(fixture.srId)}&filter=all`)
    await expect(page.getByRole('button', { name: 'Find PDFs' })).toBeVisible()
    await expect(page.getByText('PDF required')).toBeVisible()

    await page.getByRole('button', { name: 'Find PDFs' }).click()
    const panel = page.getByText(/Background job · PDF linkage/)
    await expect(panel).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: 'Upload' })).toBeDisabled()
    await expect(page.getByText(/Background job · PDF linkage · Done/)).toBeVisible({ timeout: 30_000 })

    await page.getByTitle('Close').click()
    await expect(panel).toBeHidden()
    await expect(page.getByRole('button', { name: 'Upload' })).toBeEnabled()
    await expect(page.getByText(/PDF required · missing doi/)).toBeVisible()
  })

  test('supports pause, resume, and cancel controls', async ({ page }) => {
    let status = 'running'
    await page.route('**/api/can-sr/jobs/active', async (route) => {
      await route.fulfill({
        json: {
          jobs: status === 'done' ? [] : [{
            job_id: 'browser-control-job',
            sr_id: fixture.srId,
            sr_name: 'PDF browser E2E fixture',
            pipeline_key: 'pdf_linkage',
            step: 'pdf_linkage',
            status,
            total: 1,
            done: 0,
            skipped: 0,
            failed: 0,
          }],
        },
      })
    })
    await page.route('**/api/can-sr/jobs/pause?**', async (route) => {
      status = 'paused'
      await route.fulfill({ json: { status } })
    })
    await page.route('**/api/can-sr/jobs/resume?**', async (route) => {
      status = 'running'
      await route.fulfill({ json: { status } })
    })
    await page.route('**/api/can-sr/jobs/cancel?**', async (route) => {
      status = 'done'
      await route.fulfill({ json: { status: 'cancelled' } })
    })
    await page.goto(`/en/can-sr/l2-screen?sr_id=${encodeURIComponent(fixture.srId)}&filter=all`)
    await expect(page.getByText(/Background job · PDF linkage/)).toBeVisible()
    await page.getByTitle('Pause').click()
    await expect(page.getByText(/Paused/)).toBeVisible()
    await page.getByTitle('Resume').click()
    await expect(page.getByTitle('Pause')).toBeVisible()
    await page.getByTitle('Cancel').click()
    await expect(page.getByText(/Background job · PDF linkage/)).toBeHidden()
    await expect(page.getByRole('button', { name: 'Upload' })).toBeEnabled()
  })
})