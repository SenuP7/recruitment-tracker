/**
 * Shared values for the config and every spec. One place, so the password the
 * server seeds with and the password the tests type can never drift apart.
 */

export const PORT = Number(process.env.QA_PORT ?? 8001);
export const BASE_URL = `http://127.0.0.1:${PORT}`;

/** seed_demo creates every demo account with this password. */
export const PASSWORD = process.env.CANDIDFLOW_DEMO_PASSWORD ?? 'Qa-Candidflow-2026!';

/** Staff accounts created by `manage.py seed_demo`, one per role. */
export const STAFF = {
  recruiter: 'demo.recruiter', // Rita Nunes
  hr: 'demo.hr', // Hana Silva
  tech: 'demo.tech', // Tomas Ilic
  senior: 'demo.senior', // Sara Boateng
  lead: 'demo.lead', // Leo Marchetti
  chief: 'demo.chief', // Chiara Rossi
  admin: 'demo.admin', // Adaeze Nwosu
} as const;

/** The worked-example candidate. Has a portal login and a Technical Interview. */
export const CANDIDATE = {
  username: 'maya@demo.candidflow.example',
  firstName: 'Maya',
  fullName: 'Maya Reyes',
  role: 'Backend Engineer',
} as const;

/** Names that must never appear anywhere in the candidate portal. */
export const INTERVIEWER_NAMES = ['Hana Silva', 'Tomas Ilic', 'Chiara Rossi', 'Rita Nunes'];
