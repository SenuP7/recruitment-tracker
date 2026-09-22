/**
 * FEATURE 2 — Public careers pages and applying
 *
 * Anyone can browse open roles and apply without an account. The central
 * rule: NOTHING enters the recruitment pipeline until the applicant clicks the
 * link emailed to them. Submitting creates only a pending record recruiters
 * cannot see; confirming creates the candidate, the application and the CV,
 * scores the CV, and hands the applicant a portal account.
 *
 * The journey test below follows a real applicant end to end, including the
 * step that happens in their inbox (read from local_notifications/).
 */
import { expect, test } from '../support/fixtures';
import { CANDIDATE, STAFF } from '../support/constants';
import { buildPdf, readConfirmationPath, signInStaff, uniqueEmail } from '../support/helpers';

const ROLE = 'Platform Engineer';

test.describe('Feature 2: Careers and public applications', () => {
  test('the careers page lists the open roles', async ({ page }) => {
    await page.goto('/careers/');

    await expect(page.getByRole('heading', { level: 1, name: 'Open roles' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Backend Engineer', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: ROLE, exact: true })).toBeVisible();
  });

  test('a role page shows the requirements and links to the form', async ({ page }) => {
    await page.goto('/careers/');
    await page.getByRole('link', { name: ROLE, exact: true }).click();

    await expect(page.getByRole('heading', { level: 1, name: ROLE })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Required' })).toBeVisible();
    await expect(page.getByText('Kubernetes').first()).toBeVisible();

    await page.getByRole('link', { name: /Apply now/ }).click();
    await expect(page.getByRole('heading', { level: 1, name: `Apply for ${ROLE}` })).toBeVisible();
  });

  test('an empty submission is refused field by field', async ({ page }) => {
    await openApplyForm(page);
    await page.getByRole('button', { name: 'Send my application' }).click();

    await expect(page.getByText('Tell us your first name.')).toBeVisible();
    await expect(page.getByText('Tell us your last name.')).toBeVisible();
    await expect(page.getByText('Enter an email address we can reach you at.')).toBeVisible();
    await expect(page.getByText('Please select a CV file.')).toBeVisible();
    await expect(page.getByText("Please confirm you've read how we use your data.")).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Check your email' })).toHaveCount(0);
  });

  test('a file named .pdf that is not really a PDF is refused', async ({ page }) => {
    await openApplyForm(page);
    await fillApplication(page, {
      email: uniqueEmail('fake-pdf'),
      cv: { name: 'cv.pdf', mimeType: 'application/pdf', buffer: Buffer.from('this is plain text, not a PDF') },
    });
    await page.getByRole('button', { name: 'Send my application' }).click();

    await expect(page.getByText("That file doesn't look like a real PDF or Word document")).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Check your email' })).toHaveCount(0);
  });

  test('an address that already has an account gets the same page as a new one', async ({ page }) => {
    // Saying "you've already applied" would reveal who is in the pipeline.
    await openApplyForm(page);
    await fillApplication(page, { email: CANDIDATE.username });
    await page.getByRole('button', { name: 'Send my application' }).click();

    await expect(page.getByRole('heading', { level: 1, name: 'Check your email' })).toBeVisible();
  });

  test('full journey: apply, stay invisible until confirmed, confirm by email, get a portal account', async ({
    page,
    browser,
  }) => {
    const email = uniqueEmail('journey');
    const lastName = `Journey${Date.now().toString().slice(-6)}`;

    // 1. Apply.
    await openApplyForm(page);
    await fillApplication(page, { email, lastName });
    await page.getByRole('button', { name: 'Send my application' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Check your email' })).toBeVisible();
    await expect(page.getByText(email)).toBeVisible();

    // 2. Before confirmation a recruiter must not see it anywhere.
    const recruiterContext = await browser.newContext();
    const recruiter = await recruiterContext.newPage();
    await signInStaff(recruiter, STAFF.recruiter);
    // Assert on table rows, not page text: the empty state echoes the search
    // term back ("Nothing matches …"), so a text match would always find it.
    await recruiter.goto(`/candidates/?q=${lastName}`);
    await expect(recruiter.getByRole('heading', { name: 'No candidates found' })).toBeVisible();
    await expect(recruiter.locator('tbody tr').filter({ hasText: lastName })).toHaveCount(0);

    // 3. The applicant clicks the link in their inbox.
    const confirmPath = await readConfirmationPath(email);
    await page.goto(confirmPath);

    // 4. Confirming hands them straight to account set-up.
    await expect(page.getByRole('heading', { level: 1, name: 'Set up your account' })).toBeVisible();
    await page.getByLabel('Choose a password').fill('Qa!Journey-9127-xyz');
    await page.getByLabel('Confirm password').fill('Qa!Journey-9127-xyz');
    await page.getByRole('button', { name: 'Create my account' }).click();

    // 5. They are in their portal with the application they made.
    await expect(page).toHaveURL(/\/portal\//);
    await expect(page.getByText(ROLE).first()).toBeVisible();

    // 6. Now, and only now, the recruiter sees the candidate.
    await recruiter.goto(`/candidates/?q=${lastName}`);
    await expect(recruiter.locator('tbody tr').filter({ hasText: lastName })).toHaveCount(1);

    // 7. The confirmation link is single-use.
    await page.goto(confirmPath);
    await expect(page.getByRole('heading', { name: 'Set up your account' })).toHaveCount(0);

    await recruiterContext.close();
  });
});

async function openApplyForm(page: import('@playwright/test').Page) {
  await page.goto('/careers/');
  await page.getByRole('link', { name: ROLE, exact: true }).click();
  await page.getByRole('link', { name: /Apply now/ }).click();
}

async function fillApplication(
  page: import('@playwright/test').Page,
  options: {
    email: string;
    lastName?: string;
    cv?: { name: string; mimeType: string; buffer: Buffer };
  },
) {
  await page.getByLabel('First name').fill('Quinn');
  await page.getByLabel('Last name').fill(options.lastName ?? 'Tester');
  await page.getByLabel('Email address').fill(options.email);
  await page.getByLabel(/Phone number/).fill('07700 900999');
  await page.getByLabel('Your CV').setInputFiles(
    options.cv ?? {
      name: 'quinn-cv.pdf',
      mimeType: 'application/pdf',
      buffer: buildPdf('Quinn Tester Platform Engineer AWS Docker Kubernetes Python PostgreSQL'),
    },
  );
  await page.getByLabel(/Anything you'd like us to know/).fill('Applied by the Playwright QA suite.');
  await page.locator('#id_accept_terms').check();
}
