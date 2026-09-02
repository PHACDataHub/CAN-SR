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
  const email = `reference-dedup-${suffix}@example.com`
  const password = 'ReferenceDedupPass123'
  const register = await request.post(`${backend}/auth/register`, {
    data: {
      email,
      full_name: 'Reference Dedup E2E',
      password,
      confirm_password: password,
    },
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
      name: 'Reference dedup E2E fixture',
      description: 'Temporary Playwright fixture',
      criteria_yaml:
        'schema_version: 2\ncitation_fields:\n  title: Title\n  abstract: Abstract\n  doi: DOI\n  l1_include: []\nl1: []\nl2: []\nparameters: []\n',
    },
  })
  expect(create.ok(), await create.text()).toBeTruthy()

  const srId = (await create.json()).id as string
  const upload = await request.post(`${backend}/cite/${srId}/imports`, {
    headers: auth,
    multipart: {
      commit_key: `reference-dedup-${suffix}`,
      title_header: 'title',
      abstract_header: 'abstract',
      include_duplicates: 'true',
      file: {
        name: 'dedup-citations.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(
          [
            'title,abstract,doi,year,journal',
            'Shared Trial,This study compares outcomes,10.1000/shared,2024,Journal A',
            'Shared Trial,This study compares outcomes,10.1000/shared,2024,Journal A',
            'Unique Trial,Different abstract,10.1000/unique,2023,Journal B',
          ].join('\n'),
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

test.describe('Reference deduplication workflow', () => {
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

  test('starts dedup quickly and completes through polling', async ({ page, request }) => {
    const dedupResponse = await request.post(`${backend}/cite/${fixture.srId}/citations/workspace/duplicate-runs`, {
      headers: { Authorization: `Bearer ${fixture.token}` },
    })
    expect(dedupResponse.ok(), await dedupResponse.text()).toBeTruthy()
    const dedupPayload = await dedupResponse.json()
    expect(dedupPayload.run_id).toBeTruthy()
    expect(['running', 'succeeded']).toContain(dedupPayload.status)

    if (dedupPayload.status === 'running') {
      await expect.poll(async () => {
        const pollResponse = await request.get(
          `${backend}/cite/${fixture.srId}/citations/workspace/duplicate-runs/${dedupPayload.run_id}`,
          { headers: { Authorization: `Bearer ${fixture.token}` } },
        )
        expect(pollResponse.ok(), await pollResponse.text()).toBeTruthy()
        const payload = await pollResponse.json()
        return payload.status
      }, { timeout: 30_000, intervals: [500, 1_000, 2_000] }).toBe('succeeded')
    }

    await page.goto(`/en/can-sr/references?sr_id=${encodeURIComponent(fixture.srId)}`)
    await expect(page.getByText('References workspace')).toBeVisible()
  })
})