# Proposed cloud architecture (editable source)

**Status:** Proposed planning architecture, not deployed or verified. The PNG [`cloud-architecture-draft.png`](cloud-architecture-draft.png) is an inaccurate prior draft, retained but superseded by this Mermaid source.

## Logical workflow

```mermaid
flowchart LR
  B[Authenticated browser]
  API[FastAPI API]
  N[Nginx and React on public EC2]
  S3[(Private S3: PDF uploads and current saved PDF)]
  DB[(Private RDS PostgreSQL and planned pgvector)]
  EQ[[SQS extraction queue]]
  EDQ[[Extraction DLQ]]
  X[PDF extraction and cleanup process]
  V[[SQS embedding queue]]
  VDQ[[Embedding DLQ]]
  E[MiniLM CPU embedding process]

  B -->|HTTPS submit, poll, browse, review, save| N
  N --> API
  API -->|Upload candidate; prior PDF stays current until explicit save| S3
  API -->|After S3 upload: DB transaction with extraction task and outbox row| DB
  DB -.->|Durable unsent row; publisher placement TBD| EQ
  API -->|202 task status; owner-scoped polling| B
  EQ -->|Poll and deliver extraction task| X
  X -->|Read submitted PDF| S3
  X -->|Reviewable draft and extraction status only| DB
  EQ -->|Redrive after maxReceiveCount TBD| EDQ
  B -->|Human review, edit, explicit save| API
  API -->|DB transaction: approved revision, current PDF reference, embedding PENDING, durable task and outbox row| DB
  DB -.->|Durable unsent row; publisher placement TBD| V
  V -->|Poll and deliver embedding task| E
  E -->|Read current revision metadata| DB
  E -->|Write vectors and embedding status for current revision only| DB
  V -->|Redrive after maxReceiveCount TBD| VDQ
  B -->|View recommendations| API
  API -->|Match only current revision with READY vectors; query jobs| DB
  DB -->|Matching results| API
```

**Proposed, not implemented or verified:** the API durably saves the reviewed content as a new approved revision, promotes that revision's already-uploaded S3 PDF reference in the same database transaction, sets embedding status to `PENDING`, and records its pending task and outbox instruction. The S3 object upload is not atomic with the database. Delete a previous PDF object only after the database reference change commits; abandoned review leaves the previous PDF current. A publisher retries durable unsent outbox rows and marks each sent only after SQS acknowledges; a crash after commit and before publish therefore leaves recoverable work. Duplicate publication remains possible and task handling must be idempotent. The same outbox pattern can accept an extraction task after the S3 object exists and the task/outbox transaction commits. Publisher placement is TBD and does not imply a new AWS service.

Extraction writes only the reviewable draft and extraction status; it is never the initial writer of approved content. The proposed processing policy allows up to three attempts total, including the initial attempt, for transient failures; an unusable PDF is terminal. SQS receive count does not equal worker execution count, so `maxReceiveCount` needs tuning with visibility timeout. The embedding worker writes vectors and embedding status only for the current revision, with the revision and task identity/status checked in the atomic database commit after computation. A retry creates a new task for the currently saved revision, reuses its PDF reference without reupload, and leaves the failed task unchanged. Late or obsolete workers discard results without changing current status. Reconciliation must distinguish queued work still waiting from stuck or failed work using task state/lease-aware checks; cadence, lease, and timeout remain TBD. If embedding fails, retain the approved content and PDF, expose a failed preparation state with retry, and keep matching unavailable. Matching may use only the current revision after its embedding status is `READY`, so stale vectors are never mixed with current content. Queue parameter values and cleanup interval are unresolved.

Resilience verification should cover a crash after database commit but before publication, duplicate publication, worker crash, attempt A completing after revision B is saved, an obsolete attempt completing after retry, and embedding failure retaining the reviewed content and PDF reference.

## Network placement

```mermaid
flowchart TB
  Internet((Internet))
  subgraph AWS[ AWS us-east-1 planning region ]
    subgraph VPC[One VPC; subnet CIDRs and security-group rules TBD]
      IGW[Internet gateway]
      subgraph Public[Public subnet]
        API[Public EC2: Nginx, React, FastAPI]
        NAT[NAT gateway, provisional]
      end
      subgraph Private[Private subnets]
        Worker[Private EC2: extraction and embedding processes]
        RDS[(RDS PostgreSQL Single-AZ)]
      end
      Endpoint[S3 gateway endpoint]
    end
    subgraph Managed[Regional AWS services outside the VPC]
      S3[(Private S3 bucket)]
      Q1[[SQS extraction queue]]
      Q1D[[Extraction DLQ]]
      Q2[[SQS embedding queue]]
      Q2D[[Embedding DLQ]]
      ECR[ECR pinned application and model images]
      CW[CloudWatch logs and metrics]
    end
  end

  Internet -->|HTTPS via DuckDNS hostname; exact hostname, certificate, OAuth callback TBD| IGW
  IGW --> API
  RDS -.->|Outbox publish to extraction queue; publisher placement and transport TBD| Q1
  RDS -.->|Outbox publish to embedding queue; publisher placement and transport TBD| Q2
  API -->|Logical upload/download; transport via S3 gateway endpoint| Endpoint
  API -->|Private database connection| RDS
  Q1 -->|Worker polls and receives| Worker
  Q2 -->|Worker polls and receives| Worker
  Worker -->|Private database connection| RDS
  Worker -->|Logical PDF read; transport via S3 gateway endpoint| Endpoint
  Endpoint --> S3
  Q1 -->|Redrive after maxReceiveCount TBD| Q1D
  Q2 -->|Redrive after maxReceiveCount TBD| Q2D
  Worker -.->|HTTPS SQS public endpoint polling transport| NAT
  NAT -.->|Worker outbound route| IGW
  IGW -.-> Internet
  Internet -.->|SQS public endpoint| Q1
  Internet -.->|SQS public endpoint| Q2
  API -.->|Logs and metrics| CW
  Worker -.->|Logs and metrics| CW
  API -.->|Image pull during setup/update| ECR
  Worker -.->|Image pull during setup/update| ECR
```

**Edge key:** labels identify logical workflow and transport paths. S3 and SQS are regional AWS services outside the VPC. The arrows from PostgreSQL to SQS represent the logical outbox publication path; the publisher's placement and transport are TBD, and the diagram does not add a separate AWS service or claim that the API request publishes directly. The private worker polls SQS public endpoints through the provisional NAT gateway; S3 reads and writes use the separate S3 gateway endpoint. SQS redrives messages according to a still-undecided `maxReceiveCount`, which counts receives rather than exact worker executions; retry count and visibility timeout need coordinated tuning. Workers do not publish directly to DLQs. ECR access path, exact endpoint/security rules, and deployment-time image-pull design remain to be finalized.

RDS is planned Single-AZ. Its subnet group covers a second Availability Zone for placement; there is no standby database or HA claim. Learner Lab's supplied `LabRole` does not support a claim of custom per-component least-privilege roles. Enhanced Monitoring is unavailable in the lab; standard monitoring and CloudWatch logs/metrics are the current plan, with alarms still TBD.
