/**
 * Every spec imports `test` and `expect` from here instead of from
 * @playwright/test. The only difference: an automatic fixture that resets the
 * QA database once at the start of every test run.
 *
 * Why not reset when the server starts? Because the server's lifetime is not
 * the run's lifetime. VS Code's Playwright extension keeps one QA server alive
 * across many runs, so a reset tied to server start happens once, and the
 * second run finds a screening outcome already decided and a delegation
 * already answered. Resetting per run makes one test, one feature and the
 * whole suite behave the same way, from the terminal or from the extension.
 *
 * Worker-scoped and the suite uses one worker, so this runs once per run.
 */
import { execFileSync } from 'child_process';
import path from 'path';
import { test as base, expect } from '@playwright/test';
import { PASSWORD, PORT, PYTHON, QA_ROOT } from './constants';

export const test = base.extend<{}, { freshData: void }>({
  freshData: [
    async ({}, use) => {
      execFileSync(PYTHON, [path.join(QA_ROOT, 'server', 'reset_qa_data.py')], {
        cwd: QA_ROOT,
        env: { ...process.env, QA_PORT: String(PORT), CANDIDFLOW_DEMO_PASSWORD: PASSWORD },
        stdio: 'pipe',
        timeout: 120_000,
      });
      await use();
    },
    { scope: 'worker', auto: true },
  ],
});

export { expect };
