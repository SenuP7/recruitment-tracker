/**
 * FEATURE 4 — Managing candidates and applications
 *
 * The recruiter's daily work: find people, move through the pipeline by
 * stage, open a record, and export what they're looking at. Plus the checks
 * that keep it safe — the export follows the filters on screen, and a role
 * without the permission can't add candidates.
 */
import fs from 'fs';
import { expect, test } from '@playwright/test';
import { CANDIDATE, STAFF } from '../support/constants';
import { signInStaff } from '../support/helpers';

const COHORT = ['Nadia Haddad', 'Daniel Okoro', 'Ines Duarte', 'Marcus Webb', 'Aiko Tanaka', 'Tobias Lindqvist'];

test.describe('Feature 4: Candidates and applications', () => {
  test.beforeEach(async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await expect(page).toHaveURL(/\/dashboard\/$/);
  });

  test('the candidate list shows everyone in the pipeline', async ({ page }) => {
    await page.goto('/candidates/');

    await expect(page.getByRole('columnheader', { name: 'Candidate' })).toBeVisible();
    for (const name of [CANDIDATE.fullName, ...COHORT]) {
      await expect(page.locator('tbody tr').filter({ hasText: name })).toHaveCount(1);
    }
  });

  test('search narrows the list to matching candidates', async ({ page }) => {
    await page.goto('/candidates/');
    await page.getByPlaceholder('Search by name or email').fill('Okoro');
    await page.getByPlaceholder('Search by name or email').press('Enter');

    await expect(page).toHaveURL(/q=Okoro/);
    await expect(page.locator('tbody tr').filter({ hasText: 'Daniel Okoro' })).toHaveCount(1);
    await expect(page.locator('tbody tr').filter({ hasText: 'Nadia Haddad' })).toHaveCount(0);
  });

  test('stage tabs filter applications by where they are in the pipeline', async ({ page }) => {
    await page.goto('/candidates/applications/');
    const tabs = page.getByRole('navigation', { name: 'Filter by stage' });

    await tabs.getByRole('link', { name: /^Rejected/ }).click();
    await expect(page).toHaveURL(/tab=rejected/);
    await expect(page.locator('tbody tr').filter({ hasText: 'Tobias Lindqvist' })).toHaveCount(1);
    await expect(page.locator('tbody tr').filter({ hasText: 'Nadia Haddad' })).toHaveCount(0);

    await tabs.getByRole('link', { name: /^Applied/ }).click();
    await expect(page.locator('tbody tr').filter({ hasText: 'Nadia Haddad' })).toHaveCount(1);
    await expect(page.locator('tbody tr').filter({ hasText: 'Tobias Lindqvist' })).toHaveCount(0);
  });

  test('an application record brings together the candidate, CV score and their message', async ({ page }) => {
    await page.goto(`/candidates/applications/?q=Reyes`);
    await page.locator('tbody tr[data-href]').filter({ hasText: CANDIDATE.fullName }).first().click();

    await expect(page).toHaveURL(/\/candidates\/applications\/\d+\/$/);
    await expect(page.getByText(CANDIDATE.fullName).first()).toBeVisible();
    await expect(page.getByText(CANDIDATE.role).first()).toBeVisible();
    // The applicant's own words, shown to the team.
    await expect(page.getByText("I've spent the last six years on Python and Django services")).toBeVisible();
    // The CV was scored through the real code path.
    await expect(page.getByText('Missing required')).toBeVisible();
    await expect(page.getByRole('link', { name: /Full result/ })).toBeVisible();
  });

  test('CSV export downloads exactly the rows on screen', async ({ page }) => {
    await page.goto('/candidates/?q=Okoro');

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Export' }).click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/^candidates-.*\.csv$/);
    const csv = fs.readFileSync((await download.path())!, 'utf-8');
    const [header, ...rows] = csv.trim().split(/\r?\n/);

    expect(header).toContain('First name');
    expect(header).toContain('Email');
    // The search on screen is honoured: one row, and it's the right person.
    expect(rows).toHaveLength(1);
    expect(rows[0]).toContain('Okoro');
    expect(csv).not.toContain('Haddad');
  });

  test('adding a candidate with an email already in use names the existing record', async ({ page }) => {
    await page.goto('/candidates/add/');
    await page.getByLabel(/^First name/).fill('Someone');
    await page.getByLabel(/^Last name/).fill('Else');
    await page.getByLabel(/^Email/).fill(CANDIDATE.username);
    await page.getByLabel(/^Phone/).fill('07700 900000');
    await page.getByLabel(/^Department/).selectOption({ index: 1 });
    await page.getByRole('button', { name: /save|create|add candidate/i }).click();

    // Not saved: the form comes back and points at the person who has that address.
    await expect(page).toHaveURL(/\/candidates\/add\/$/);
    await expect(page.getByRole('link', { name: CANDIDATE.fullName })).toBeVisible();
  });

  test('a Technical Interviewer can read candidates but cannot add one', async ({ page }) => {
    await page.context().clearCookies();
    await signInStaff(page, STAFF.tech);

    await page.goto('/candidates/');
    await expect(page.locator('tbody tr').first()).toBeVisible();

    const response = await page.goto('/candidates/add/');
    expect(response?.status()).toBe(403);
  });
});
