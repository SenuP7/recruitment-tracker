/**
 * FEATURE 3 — The candidate portal
 *
 * Candidates follow their own applications at /portal/. Two things matter
 * most here, and both are privacy guarantees rather than features:
 *
 *   1. A candidate sees only their own records. No portal URL takes a
 *      candidate id, and an application id that isn't theirs is a 404.
 *   2. A candidate never sees interview feedback, CV match scores, interviewer
 *      names, or any sign of other applicants.
 */
import { expect, test } from '@playwright/test';
import { CANDIDATE, INTERVIEWER_NAMES, STAFF } from '../support/constants';
import { idFromHref, signInCandidate, signInStaff } from '../support/helpers';

// Verbatim from seed_demo: the HR interviewer's feedback on Maya, and the reply.
const MAYAS_FEEDBACK = 'Explained the reporting API rewrite clearly';
const MAYAS_FEEDBACK_REPLY = 'Worth pushing on system design';

test.describe('Feature 3: Candidate portal', () => {
  test.beforeEach(async ({ page }) => {
    await signInCandidate(page, CANDIDATE.username);
    await expect(page).toHaveURL(/\/portal\/$/);
  });

  test('the overview lists the candidate’s own application and its stage', async ({ page }) => {
    await expect(page.getByRole('heading', { name: `Hello ${CANDIDATE.firstName}.` })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'All applications' })).toBeVisible();
    await expect(page.getByRole('link', { name: CANDIDATE.role }).first()).toBeVisible();
    await expect(page.getByText('Technical Interview').first()).toBeVisible();
  });

  test('the application page shows progress and the upcoming interview', async ({ page }) => {
    await page.getByRole('link', { name: CANDIDATE.role }).first().click();

    await expect(page.getByRole('heading', { level: 1, name: CANDIDATE.role })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Where your application is' })).toBeVisible();
    await expect(page.locator('.stepper .step')).not.toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Your interviews' })).toBeVisible();
    await expect(page.getByText('Technical').first()).toBeVisible();
  });

  test('no feedback, scores or interviewer names ever reach the candidate', async ({ page }) => {
    // Check both portal pages, on the whole rendered text.
    const pages = [page.url()];
    await page.getByRole('link', { name: CANDIDATE.role }).first().click();
    pages.push(page.url());

    for (const url of pages) {
      await page.goto(url);
      const text = await page.locator('body').innerText();

      for (const name of INTERVIEWER_NAMES) {
        expect(text, `interviewer name "${name}" leaked on ${url}`).not.toContain(name);
      }
      expect(text, `feedback leaked on ${url}`).not.toContain(MAYAS_FEEDBACK);
      expect(text, `feedback reply leaked on ${url}`).not.toContain(MAYAS_FEEDBACK_REPLY);
      expect(text.toLowerCase(), `a match score leaked on ${url}`).not.toMatch(/match score|cv match|\d+\s?% match/);
      expect(text, `a recommendation leaked on ${url}`).not.toMatch(/Recommendation|Strong pass/);
      // The delegation reason seeded on Maya's technical round.
      expect(text, `delegation detail leaked on ${url}`).not.toContain('conference');
    }
  });

  test('another candidate’s application id returns 404, not their data', async ({ page, browser }) => {
    // Find a real application that belongs to someone else, as a recruiter.
    const staffContext = await browser.newContext();
    const recruiter = await staffContext.newPage();
    await signInStaff(recruiter, STAFF.recruiter);
    await recruiter.goto('/candidates/applications/?q=Haddad');
    const row = recruiter.locator('tbody tr[data-href]').first();
    await expect(row).toBeVisible();
    const otherId = idFromHref(await row.getAttribute('data-href'));
    await staffContext.close();

    // Maya asks for it directly.
    const response = await page.goto(`/portal/applications/${otherId}/`);
    expect(response?.status()).toBe(404);
    await expect(page.getByText('Haddad')).toHaveCount(0);
  });

  test('a candidate account is kept out of every staff page', async ({ page }) => {
    // CandidatePortalMiddleware: defence in depth, even if a permission were
    // ever granted to the Candidate group by mistake.
    for (const path of ['/dashboard/', '/candidates/', '/candidates/applications/', '/cv-screening/results/', '/interviews/']) {
      await page.goto(path);
      await expect(page, `${path} should not be reachable by a candidate`).not.toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByText('Nadia Haddad')).toHaveCount(0);
    }
  });
});
