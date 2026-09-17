# Recruitment Tracker — Notification Service

A decoupled, asynchronous, AWS-native email notification pipeline for the
Recruitment Tracker Django app. It does **not** run inside the Elastic
Beanstalk request/response cycle: Django only ever publishes a small JSON
event to SQS (`sqs:SendMessage`, nothing else) and returns immediately. A
separate Lambda function does everything else — rendering the email,
sending it via SES, and logging the attempt to DynamoDB.

See [`docs/sequence-diagram.md`](docs/sequence-diagram.md) for the full flow
(including the retry/DLQ path) and [`docs/test-cases.md`](docs/test-cases.md)
for the formal test case list.

## Architecture

```
Django (EB)  --sqs:SendMessage-->  SQS Queue  --trigger-->  Lambda  --ses:SendEmail-->  SES  --> candidate's inbox
                                        |                      |
                                        | (after maxReceiveCount            +--dynamodb:PutItem--> Audit log table
                                        |  failed attempts)
                                        v
                                   Dead Letter Queue --> CloudWatch Alarm --> SNS --> alert email
```

- **SQS** (`recruitment-tracker-notifications`) + **DLQ**
  (`recruitment-tracker-notifications-dlq`) — the queue and its dead-letter
  queue, `maxReceiveCount=3`.
- **Lambda** (`recruitment-tracker-notifier`) — one Python function, triggered
  by SQS with `BatchSize=1` (deliberate — see the docstring in
  `lambda/notifier/handler.py`). Selects an email template by `event_type` via
  a small registry (`lambda/notifier/templates.py`), sends via SES, logs the
  attempt to DynamoDB.
- **SES** — one verified sender identity. Runs in SES **sandbox mode** by
  default (no production-access request needed for a student project) — both
  sender and every recipient must be individually verified while in sandbox.
- **DynamoDB** (`recruitment-tracker-notifications-audit`) — one item per
  delivery *attempt* (partition key `notification_id`, sort key `sent_at`), so
  retries of one logical event are all queryable together.
- **CloudWatch alarm + SNS** — fires when the DLQ has >=1 message, emails the
  configured alert address.
- **IAM** — two separate, narrowly-scoped policies: the Lambda's execution role
  (SQS receive/delete on the main queue, `ses:SendEmail` scoped to the sender
  identity, `dynamodb:PutItem` scoped to the audit table, CloudWatch Logs), and
  a standalone `RecruitmentTrackerNotificationPublish` managed policy
  (`sqs:SendMessage` only) meant for the Django/EB app — see
  [Connecting Django](#connecting-django) below for why this isn't
  auto-attached.

Why **AWS SAM** over Terraform: `AWS::Serverless::Function` + an `SQS` event
source auto-generates the event source mapping *and* its IAM permissions;
`sam local invoke` lets the handler logic be exercised with zero AWS
credentials; there's no separate state-backend to stand up (state lives in
CloudFormation itself). Terraform's `plan` diff is arguably clearer to explain
in a report, but that's not enough to offset the extra ceremony for a
single-function event-driven stack this size.

## Django-side integration

- `notification_client/` (repo root, plain Python package, no Django app
  needed since it has no models) — `publisher.py`'s `publish_event(...)` does
  the actual `boto3` `sqs:SendMessage` call. It never raises: any failure is
  caught, logged, and reported as `False`, and if
  `NOTIFICATIONS_SQS_QUEUE_URL` isn't configured it no-ops with a warning — so
  the rest of the app works fine on a machine with no AWS access at all.
- `candidates/signals.py` — `pre_save` on `Application` reads (never writes)
  the current DB status; `post_save` compares old vs new and, only on a real
  transition (not the initial "Applied" row), publishes
  `application_status_changed` via `transaction.on_commit(...)` — so a status
  change inside a transaction that later rolls back never sends an email.
- `interviews/signals.py` — `post_save(created=True)` on `Interview` publishes
  `interview_scheduled`, same commit-gating.
- Both apps' `apps.py` gained a `ready()` hook importing their `signals`
  module — Django's standard way to register signal handlers.

Adding a third trigger later: add one `TemplateSpec` to
`lambda/notifier/templates.py`, one `.txt` body file next to the existing two,
and one new Django signal that calls `publish_event(...)`. Nothing else
changes — `handler.py`'s dispatch is a single dict lookup, no branching logic
to extend.

## Deploying

Needs the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
(already installed on this machine) and AWS credentials with permission to
create the resources above (`aws configure` first if you haven't).

```bash
cd notification-service
sam build
sam deploy --guided
```

On first run, `sam deploy --guided` will prompt for the stack name, region,
and the `SenderEmail` parameter (an email address you control — SES will send
it a verification link right after the stack creates; click it before testing
sends). `AlertEmail` defaults to the value in `samconfig.toml`; override it if
you want alarms going somewhere else. Confirm the changeset when prompted.

**SES sandbox note**: while in sandbox mode (the default, no action needed),
you must also verify any recipient address you want to actually send to:

```bash
aws ses verify-email-identity --email-address candidate@example.com --region ap-southeast-1
```

(They'll get a verification email too, before they can receive real
notifications. This is an SES sandbox limitation, not something this stack
controls — requesting SES production access removes it, out of scope for a
student deliverable.)

### Connecting Django

After deploy, `sam deploy` prints stack outputs including `QueueUrl` and
`NotificationPublishPolicyArn`. Two manual steps (deliberately not automated —
see `template.yaml`'s comments on why):

1. Set `NOTIFICATIONS_SQS_QUEUE_URL` (the `QueueUrl` output) and
   `NOTIFICATIONS_AWS_REGION` in the Django app's environment — locally via
   `.env` (see `.env.example` at the repo root), and on Elastic Beanstalk via
   its environment properties.
2. Attach the publish-only policy to the EB instance role (find its name via
   the EB console, under the environment's IAM instance profile):
   ```bash
   aws iam attach-role-policy --role-name <eb-instance-role-name> --policy-arn <NotificationPublishPolicyArn output>
   ```
   This grants `sqs:SendMessage` only — deliberately not folded into the
   existing S3 role the EB instance already has for CV storage.

Locally, if you want to exercise the real publish path without an existing AWS
CLI profile, add a personal IAM user's keys (scoped to `sqs:SendMessage` only,
same policy) as `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in `.env` — boto3
picks these up automatically. Leaving `NOTIFICATIONS_SQS_QUEUE_URL` empty is
also fine; `publish_event` just no-ops.

## Try it locally, before deploying anything

Set `NOTIFICATIONS_LOCAL_MODE=True` in the repo root's `.env` and run
`manage.py runserver` as usual. `publish_event()` will then render each
notification in-process — using the exact same template code that ships to
the real Lambda (`notification-service/lambda/notifier/templates.py`), not a
reimplementation — and write it to `local_notifications/` (gitignored)
instead of touching AWS at all:

- `local_notifications/<notification_id>.txt` — the rendered email (To/Subject/body)
- `local_notifications/audit_log.jsonl` — one JSON line per attempt, same shape as the real DynamoDB audit table

It also prints the rendered email to the `runserver` console. Change an
`Application`'s status or create an `Interview` in the running app and you'll
see it appear immediately — no AWS account, no deployment, no credentials
needed. This is the fastest way to confirm the Django-side signal wiring and
template rendering both work before you ever touch AWS.

Leave `NOTIFICATIONS_LOCAL_MODE` unset (or `False`) once you're ready to point
at the real deployed queue.

## Testing

### Lambda unit tests (pytest + moto — no AWS credentials or deployment needed)

```bash
cd notification-service
python -m venv .venv
./.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pytest -v
```

`tests/` lives outside `lambda/` on purpose — anything inside `lambda/` ships
in the Lambda deployment package (SAM's Python builder has no ignore-file
mechanism), so tests, dev-only dependencies, and this `.venv` are kept as
siblings instead. `pytest.ini`'s `pythonpath = lambda` is what still lets the
tests `from notifier import handler`.

### Template validation (no credentials needed)

```bash
sam validate --lint
sam build
```

### Local invocation (needs Docker — optional; not run as part of this build since Docker isn't installed on this machine)

```bash
sam local invoke NotifierFunction -e events/application_status_changed.json
sam local invoke NotifierFunction -e events/interview_scheduled.json
sam local invoke NotifierFunction -e events/malformed_event.json
```

### Django-side tests

```bash
DATABASE_URL="" ./venv/Scripts/python.exe manage.py test candidates interviews
```

Covers the signal-wiring behavior (TC-09/TC-10 in `docs/test-cases.md`) by
mocking `publish_event` — no AWS access needed.

### End-to-end, against the real deployed stack

See `docs/test-cases.md` TC-01 through TC-08 for the manual walkthrough once
deployed (create/edit an `Application` or `Interview` in the running Django
app, watch the email arrive, check the DynamoDB audit table). TC-05 (DLQ ->
CloudWatch -> SNS) is inherently a real-AWS test.

## AWS Free Tier cost

At a student-project demo volume (dozens to low hundreds of events), every
service here stays at **$0**:

| Service | Free tier | This project's usage |
|---|---|---|
| SQS | 1M requests/month always-free | Negligible |
| Lambda | 1M requests + 400,000 GB-seconds/month always-free | 128MB, ~1s per invocation — thousands of invocations before any cost |
| SES | 62,000 emails/month free when sent from Lambda/EC2 | Far below this for a demo |
| DynamoDB | 25GB storage + on-demand free tier always-free | `PAY_PER_REQUEST` billing, tiny item count/size |
| CloudWatch | 10 custom alarms + basic logs free | 1 alarm used |
| SNS | 1,000 email notifications/month free | Only fires when the DLQ actually has messages |

The only way to incur real cost is sustained high volume far beyond a class
project's demo/report needs, or leaving the stack running indefinitely after
the module ends — `sam delete` tears everything down cleanly when you're done.
