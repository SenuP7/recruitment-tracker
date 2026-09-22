/**
 * FEATURE 1 — Sign-in and the two sign-in doors
 *
 * Candidflow has one accounts system and two sign-in pages: staff at
 * /accounts/login/, candidates at /portal/login/. Each refuses the other's
 * accounts, and both do so only AFTER the password is verified, so neither
 * page can be used to discover which accounts exist.
 */
import { expect, test } from '@playwright/test';
import { CANDIDATE, PASSWORD, STAFF } from '../support/constants';
import { signInCandidate, signInStaff } from '../support/helpers';

test.describe('Feature 1: Sign-in and access doors', () => {
  test('a recruiter signs in and lands on the dashboard', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);

    await expect(page).toHaveURL(/\/dashboard\/$/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('every staff role can sign in', async ({ page }) => {
    for (const username of Object.values(STAFF)) {
      await page.context().clearCookies();
      await signInStaff(page, username);
      await expect(page, `${username} should reach the dashboard`).toHaveURL(/\/dashboard\/$/);
    }
  });

  test('Administrator and Department Chief can open the pages their job needs', async ({ page }) => {
    // Signing in is not enough: both roles once reached the dashboard while
    // holding zero permissions, and every page past it answered 403.
    const needs: Record<string, string[]> = {
      [STAFF.admin]: ['/candidates/', '/interviews/', '/accounts/staff/', '/accounts/audit-log/'],
      [STAFF.chief]: ['/candidates/', '/interviews/', '/positions/'],
    };
    for (const [username, paths] of Object.entries(needs)) {
      await page.context().clearCookies();
      await signInStaff(page, username);
      for (const path of paths) {
        const response = await page.goto(path);
        expect(response?.status(), `${username} was refused ${path}`).toBe(200);
      }
    }
  });

  test('a wrong password and an unknown user get the identical message', async ({ page }) => {
    // If these differed, the form would tell an attacker which usernames exist.
    await signInStaff(page, STAFF.recruiter, 'definitely-not-the-password');
    const wrongPassword = await page.getByRole('alert').innerText();

    await signInStaff(page, 'nobody.at.all', 'definitely-not-the-password');
    const unknownUser = await page.getByRole('alert').innerText();

    await expect(page).toHaveURL(/\/accounts\/login\/$/);
    expect(unknownUser.trim()).toBe(wrongPassword.trim());
  });

  test('the staff door refuses a candidate account', async ({ page }) => {
    await signInStaff(page, CANDIDATE.username);

    await expect(page.getByRole('alert')).toContainText("That's a candidate account");
    await expect(page).toHaveURL(/\/accounts\/login\/$/);
  });

  test('the candidate door refuses a staff account', async ({ page }) => {
    await signInCandidate(page, STAFF.recruiter);

    await expect(page.getByRole('alert')).toContainText("That's a team account");
    await expect(page).toHaveURL(/\/portal\/login\/$/);
  });

  test('a candidate signs in through their own door and reaches the portal', async ({ page }) => {
    await signInCandidate(page, CANDIDATE.username);

    await expect(page).toHaveURL(/\/portal\/$/);
    await expect(page.getByRole('heading', { name: `Hello ${CANDIDATE.firstName}.` })).toBeVisible();
  });

  const STAFF_PAGES = [
    '/dashboard/',
    '/candidates/',
    '/candidates/applications/',
    '/positions/',
    '/cv-screening/results/',
    '/interviews/',
    '/accounts/audit-log/',
  ];

  test('signed-out visitors cannot open any staff page', async ({ page }) => {
    // The security property: whatever the page does, it must not serve data.
    for (const path of STAFF_PAGES) {
      const response = await page.goto(path);
      const url = page.url();
      const redirectedToSignIn = /\/accounts\/login\/\?next=/.test(url);
      const refused = response?.status() === 403;
      expect(redirectedToSignIn || refused, `${path} served content to a signed-out visitor`).toBe(true);
      await expect(page.getByText(CANDIDATE.fullName)).toHaveCount(0);
    }
  });

  test('signed-out visitors are redirected to sign in, not shown a 403', async ({ page }) => {
    // Found by this suite (2026-09-22) and fixed: candidates, applications,
    // positions and interviews used to answer a signed-out visitor with a bare
    // "403 Forbidden" and no way to sign in. With an 8-hour idle timeout that
    // made every bookmarked link a dead end.
    for (const path of STAFF_PAGES) {
      await page.goto(path);
      await expect(page, `${path} should redirect to sign-in`).toHaveURL(/\/accounts\/login\/\?next=/);
    }
  });

  test('after signing in from a redirect, you land on the page you asked for', async ({ page }) => {
    await page.goto('/candidates/');
    await expect(page).toHaveURL(/\/accounts\/login\/\?next=%2Fcandidates%2F|\/accounts\/login\/\?next=\/candidates\//);

    await page.getByLabel('Username').fill(STAFF.recruiter);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();

    await expect(page).toHaveURL(/\/candidates\/$/);
  });

  test('a signed-in user without the permission gets an explained 403', async ({ page }) => {
    // Candidates can't reach staff pages at all (the portal middleware moves
    // them), so use a staff role missing one permission: a Technical
    // Interviewer may read candidates but not add them.
    await signInStaff(page, STAFF.tech);
    const response = await page.goto('/candidates/add/');

    expect(response?.status()).toBe(403);
    await expect(page.getByRole('heading', { name: "You don't have access to this page." })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Back to your dashboard' })).toBeVisible();
  });

  test('logging out ends the session', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await expect(page).toHaveURL(/\/dashboard\/$/);

    await page.getByRole('button', { name: 'Log out' }).click();
    await expect(page).toHaveURL(/\/$/); // LOGOUT_REDIRECT_URL is the public home page

    // The old session must no longer open staff pages.
    await page.goto('/dashboard/');
    await expect(page).toHaveURL(/\/accounts\/login\/\?next=/);
  });

  test('the password shown is not accepted with different casing', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter, PASSWORD.toUpperCase());
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/accounts\/login\/$/);
  });
});
