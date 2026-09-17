# Notification Flow — Sequence Diagram

Covers both the happy path and the failure/DLQ path for a single event (e.g. an
`Application.status` change). `interview_scheduled` follows the identical shape,
just triggered from `Interview`'s `post_save` signal instead.

```mermaid
sequenceDiagram
    participant U as Recruiter (browser)
    participant D as Django (EB)
    participant Q as SQS Queue
    participant L as Lambda (notifier)
    participant S as SES
    participant DB as DynamoDB (audit log)
    participant DLQ as Dead Letter Queue
    participant CW as CloudWatch Alarm
    participant SNS as SNS Topic
    participant Admin as Project admin (email)

    U->>D: Change Application.status (HTTP POST)
    D->>D: pre_save reads old status
    D->>D: post_save compares old vs new
    D->>D: transaction.on_commit(publish_event)
    D-->>U: 200/redirect (response NOT blocked on notification)
    Note over D,Q: publish_event() only fires after the DB transaction commits

    D->>Q: sqs:SendMessage (event_type, recipient, context)

    par Happy path
        Q->>L: SQS trigger (BatchSize=1)
        L->>L: templates.render(event_type, context)
        L->>S: ses:SendEmail
        S-->>L: MessageId
        L->>DB: dynamodb:PutItem (status=SENT)
        L-->>Q: success -> message deleted from queue
        S-->>Admin: (candidate receives the email)
    and Failure / retry path
        Q->>L: SQS trigger (attempt 1)
        L->>S: ses:SendEmail
        S-->>L: throttling / transient error
        L->>DB: dynamodb:PutItem (status=FAILED, attempt 1)
        L--xQ: exception re-raised -> message NOT deleted
        Note over Q,L: visibility timeout expires, SQS redelivers
        Q->>L: SQS trigger (attempt 2..N, up to maxReceiveCount)
        L->>DB: dynamodb:PutItem (status=FAILED, attempt N)
        Q->>DLQ: maxReceiveCount exceeded -> message moved to DLQ
        DLQ->>CW: ApproximateNumberOfMessagesVisible >= 1
        CW->>SNS: alarm fires
        SNS->>Admin: alert email
    end
```

## Poison-pill path (not shown above for clarity)

If `event_type` is unrecognized or the message is missing required template
context fields, the Lambda treats this as unrecoverable: it logs a `FAILED`
entry to DynamoDB and returns normally (does **not** raise), so SQS deletes the
message immediately without redelivery. Retrying a malformed message can never
succeed, so it deliberately skips the DLQ path above rather than wasting
`maxReceiveCount` attempts on it.
