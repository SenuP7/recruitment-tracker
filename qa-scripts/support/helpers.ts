import fs from 'fs';
import path from 'path';
import { expect, type Page } from '@playwright/test';
import { PASSWORD } from './constants';

/** Signs in through the staff door, exactly as a person would. */
export async function signInStaff(page: Page, username: string, password: string = PASSWORD) {
  await page.goto('/accounts/login/');
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
}

/** Signs in through the candidate door (/portal/login/). */
export async function signInCandidate(page: Page, username: string, password: string = PASSWORD) {
  await page.goto('/portal/login/');
  await page.getByLabel('Email address or username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

/**
 * A minimal but genuinely valid one-page PDF containing `text`.
 *
 * Built in memory rather than committed as a fixture: the server really
 * parses it (signature check on upload, pypdf text extraction and keyword
 * scoring on confirmation), so a hand-built file proves more than a stored
 * binary nobody looks at.
 */
export function buildPdf(text: string): Buffer {
  const safe = text.replace(/[()\\]/g, ' ');
  const content = `BT /F1 12 Tf 72 720 Td (${safe}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];

  let body = '%PDF-1.4\n';
  const offsets: number[] = [];
  objects.forEach((obj, i) => {
    offsets.push(Buffer.byteLength(body));
    body += `${i + 1} 0 obj\n${obj}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) body += `${String(off).padStart(10, '0')} 00000 n \n`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

/** A unique address per run, so tests never collide with each other or a previous run. */
export function uniqueEmail(prefix: string): string {
  return `${prefix}.${Date.now()}.${Math.floor(Math.random() * 1e6)}@qa.candidflow.example`;
}

const MAILBOX = path.resolve(__dirname, '..', '..', 'local_notifications');

/**
 * Reads the confirmation link from the email the app "sent" to `email`.
 *
 * The QA server runs notifications in local mode, which renders the real
 * Lambda template and writes it to local_notifications/<id>.txt instead of
 * calling SES. Reading it back is what lets one test cover the whole journey,
 * including the step a real applicant takes in their inbox.
 *
 * Returns the path only (e.g. /apply/confirm/<token>/), so it works whatever
 * host the link was built with.
 */
export async function readConfirmationPath(email: string): Promise<string> {
  let found = '';
  await expect
    .poll(
      () => {
        if (!fs.existsSync(MAILBOX)) return '';
        const files = fs
          .readdirSync(MAILBOX)
          .filter((f) => f.endsWith('.txt'))
          .map((f) => path.join(MAILBOX, f))
          .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
        for (const file of files) {
          const text = fs.readFileSync(file, 'utf-8');
          if (!text.includes(`<${email}>`)) continue;
          const match = text.match(/\/apply\/confirm\/[^\s/]+\//);
          if (match) return (found = match[0]);
        }
        return '';
      },
      { message: `no confirmation email for ${email} in ${MAILBOX}`, timeout: 15_000 },
    )
    .not.toBe('');
  return found;
}

/** Pulls the numeric id out of an href like /candidates/applications/42/. */
export function idFromHref(href: string | null): number {
  const match = href?.match(/\/(\d+)\/?$/);
  if (!match) throw new Error(`no id in href: ${href}`);
  return Number(match[1]);
}
