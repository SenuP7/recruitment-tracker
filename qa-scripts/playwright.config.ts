import path from 'path';
import { defineConfig, devices } from '@playwright/test';
import { BASE_URL, PASSWORD, PORT } from './support/constants';

const REPO = path.resolve(__dirname, '..');

// The project's own virtualenv, so the server runs on exactly the Django the
// app is developed against. QA_PYTHON overrides it (e.g. in CI).
const PYTHON =
  process.env.QA_PYTHON ??
  path.join(REPO, 'venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export default defineConfig({
  testDir: './tests',

  // One worker, in order. The suite shares one SQLite database and several
  // tests change it (confirming a screening outcome, answering a delegation);
  // parallel writers would make results depend on timing.
  fullyParallel: false,
  workers: 1,

  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,

  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    // 'on', not 'only-on-failure': every passing test keeps a screenshot of
    // its final screen, attached in the HTML report (npm run report). That is
    // the visual evidence for the project report, one image per test.
    screenshot: 'on',
    video: 'retain-on-failure',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  // A fresh, isolated Candidflow for every run: new SQLite file, local-disk
  // uploads, emails written to local_notifications/. Never the developer's
  // db.sqlite3, the real Postgres, S3 or SES. See server/run_qa_server.py.
  webServer: {
    command: `"${PYTHON}" server/run_qa_server.py`,
    cwd: __dirname,
    url: `${BASE_URL}/healthz/`,
    // Deliberately false: a server already on this port could be pointed at a
    // real database, and the tests would quietly write into it.
    reuseExistingServer: false,
    timeout: 180_000,
    env: { QA_PORT: String(PORT), CANDIDFLOW_DEMO_PASSWORD: PASSWORD },
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
