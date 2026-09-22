/**
 * FEATURE 5 — CV screening
 *
 * Every CV is scored against the role's required and nice-to-have skills.
 * The score is ADVICE: uploading never passes or fails anyone. Only a person
 * with permission to change applications records the outcome, and roles
 * without it are never offered the choice. (This is the GDPR Article 22
 * position the public privacy notice describes.)
 */
import { expect, test } from '../support/fixtures';
import { STAFF } from '../support/constants';
import { signInStaff } from '../support/helpers';

// Daniel Okoro is seeded at "CV Screening": scored, awaiting a human decision.
const AWAITING_DECISION = 'Daniel Okoro';

test.describe('Feature 5: CV screening', () => {
  test('the screening list shows every scored CV with its match', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await page.goto('/cv-screening/results/');

    await expect(page.getByRole('heading', { level: 1, name: /CV screening/ })).toBeVisible();
    const rows = page.locator('tbody tr[data-href]');
    await expect(rows).not.toHaveCount(0);
    await expect(rows.filter({ hasText: 'Maya Reyes' })).toHaveCount(1);
    await expect(rows.first().locator('.score-cell .mono')).toHaveText(/^\d+%$/);
  });

  test('CVs written to differ get genuinely different scores', async ({ page }) => {
    // A screen where everyone scores the same would tell a recruiter nothing.
    await signInStaff(page, STAFF.recruiter);
    await page.goto('/cv-screening/results/');

    const scores = await page.locator('tbody tr[data-href] .score-cell .mono').allInnerTexts();
    const distinct = new Set(scores.map((s) => s.trim()));
    expect(distinct.size, `scores seen: ${scores.join(', ')}`).toBeGreaterThanOrEqual(3);
  });

  test('a result explains itself: matched and missing skills', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await page.goto('/cv-screening/results/');
    await page.getByRole('link', { name: 'Maya Reyes' }).first().click();

    await expect(page.getByRole('heading', { level: 1, name: 'Maya Reyes' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Matched skills' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Missing required skills' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Match score' })).toBeVisible();
    // seed_demo deliberately leaves one required skill out of Maya's CV.
    await expect(page.locator('.chip.dashed').first()).toBeVisible();
  });

  test('a Technical Interviewer is never offered the screening decision', async ({ page }) => {
    // Runs before the recruiter decides (the suite is serial), so the
    // application is still awaiting a decision when the interviewer looks.
    await signInStaff(page, STAFF.tech);
    await openApplication(page, AWAITING_DECISION);

    await expect(page.getByText('CV Screening').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Confirm the screening outcome' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Passed screening/ })).toHaveCount(0);
  });

  test('a recruiter reads the result and records the outcome', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await openApplication(page, AWAITING_DECISION);

    const decision = page.locator('section.screening-decision');
    await expect(decision.getByRole('heading', { name: 'Confirm the screening outcome' })).toBeVisible();
    await expect(decision.getByText('The match score is advice, not a decision.')).toBeVisible();

    await decision.getByRole('button', { name: /Passed screening/ }).click();

    await expect(page.getByText('Screening marked as passed.')).toBeVisible();
    await expect(page.locator('.badge[data-status="CV Screening Passed"]').first()).toBeVisible();
    // Decided once, and the choice is no longer offered.
    await expect(page.getByRole('heading', { name: 'Confirm the screening outcome' })).toHaveCount(0);
  });
});

async function openApplication(page: import('@playwright/test').Page, fullName: string) {
  const [first, last] = fullName.split(' ');
  await page.goto(`/candidates/applications/?q=${last}`);
  await page.locator('tbody tr[data-href]').filter({ hasText: first }).first().click();
  await expect(page).toHaveURL(/\/candidates\/applications\/\d+\/$/);
}
