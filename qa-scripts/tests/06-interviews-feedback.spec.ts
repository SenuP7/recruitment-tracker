/**
 * FEATURE 6 — Interviews, threaded feedback and delegation
 *
 * Interviewers record feedback on each round as a thread the team replies to.
 * An interviewer who can't make a round can offer it to a colleague; the round
 * stays theirs until the colleague ACCEPTS, and declining needs a reason so
 * the round can be covered.
 *
 * seed_demo gives Maya a completed HR round (feedback + one reply) and an
 * upcoming Technical round that the Technical Interviewer has offered to the
 * Department Chief.
 */
import { expect, test, type Page } from '@playwright/test';
import { CANDIDATE, STAFF } from '../support/constants';
import { signInStaff } from '../support/helpers';

// Verbatim from seed_demo. Feature 3 asserts these NEVER reach the candidate;
// asserting here that staff DO see them proves that check is not vacuous.
const HR_FEEDBACK = 'Explained the reporting API rewrite clearly';
const HR_REPLY = 'Worth pushing on system design';

test.describe('Feature 6: Interviews, feedback and delegation', () => {
  test('the interview list shows scheduled and completed rounds', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await page.goto('/interviews/');

    await expect(page.getByRole('columnheader', { name: 'Round' })).toBeVisible();
    const mayasRounds = page.locator('tbody tr[data-href]').filter({ hasText: CANDIDATE.fullName });
    await expect(mayasRounds.filter({ hasText: 'HR' })).toHaveCount(1);
    await expect(mayasRounds.filter({ hasText: 'Technical' })).toHaveCount(1);
  });

  test('the feedback thread shows the assessment and the team’s reply', async ({ page }) => {
    await signInStaff(page, STAFF.recruiter);
    await openThread(page, 'HR');

    await expect(page.getByRole('heading', { level: 1, name: 'Interview feedback' })).toBeVisible();
    await expect(page.getByText(HR_FEEDBACK)).toBeVisible();
    await expect(page.getByText(HR_REPLY)).toBeVisible();
  });

  test('an interviewer replies and the reply joins the thread', async ({ page }) => {
    const reply = `Agree with both - QA check ${Date.now()}`;
    await signInStaff(page, STAFF.hr);
    await openThread(page, 'HR');

    await page.getByRole('link', { name: 'Reply' }).first().click();
    await page.getByLabel(/^Reply/).fill(reply);
    await page.getByRole('button', { name: 'Post reply' }).click();

    await expect(page).toHaveURL(/\/interviews\/\d+\/feedback\/$/);
    await expect(page.getByText(reply)).toBeVisible();
    // Posted as the person signed in, not anonymously.
    await expect(page.locator('.message').filter({ hasText: reply }).getByText(/demo\.hr|Hana/)).toBeVisible();
  });

  test('while an offer is pending, the round stays with its owner', async ({ page }) => {
    await signInStaff(page, STAFF.tech);
    await openInterview(page, 'Technical');

    await expect(page.getByRole('heading', { name: /Who's conducting it/ })).toBeVisible();
    await expect(page.getByText(/Until it's accepted, this interview is still/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Withdraw the request' })).toBeVisible();
    // Only the person asked may answer.
    await expect(page.getByRole('button', { name: "I'll conduct it" })).toHaveCount(0);
  });

  test('declining an offer without saying why is refused', async ({ page }) => {
    await signInStaff(page, STAFF.chief);
    await openInterview(page, 'Technical');

    await page.getByRole('button', { name: "Can't take it" }).click();

    await expect(page.getByText('Please say why you can\'t take it, so it can be covered.')).toBeVisible();
    // Still pending: the choice is still there.
    await expect(page.getByRole('button', { name: "I'll conduct it" })).toBeVisible();
  });

  test('the colleague accepts and becomes the one conducting the round', async ({ page }) => {
    await signInStaff(page, STAFF.chief);
    await openInterview(page, 'Technical');

    await page.getByLabel(/A note back/).fill('Happy to cover this one.');
    await page.getByRole('button', { name: "I'll conduct it" }).click();

    await expect(page.getByText("You're down to conduct this interview.")).toBeVisible();
    await expect(page.locator('.dl-row').filter({ hasText: 'Being conducted by' })).toContainText('Chiara');
    await expect(page.getByRole('button', { name: "I'll conduct it" })).toHaveCount(0);
  });
});

async function openInterview(page: Page, round: 'HR' | 'Technical') {
  await page.goto('/interviews/');
  await page
    .locator('tbody tr[data-href]')
    .filter({ hasText: CANDIDATE.fullName })
    .filter({ hasText: round })
    .getByRole('link', { name: CANDIDATE.fullName })
    .click();
  await expect(page.getByRole('heading', { level: 1, name: new RegExp(`^${round} interview`) })).toBeVisible();
}

async function openThread(page: Page, round: 'HR' | 'Technical') {
  await openInterview(page, round);
  await page.getByRole('link', { name: /Open thread/ }).click();
  await expect(page).toHaveURL(/\/interviews\/\d+\/feedback\/$/);
}
