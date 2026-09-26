# Proposed cloud architecture (editable source)

**Status:** Proposed planning architecture, not deployed or verified. The PNG [`cloud-architecture-draft.png`](cloud-architecture-draft.png) is an inaccurate prior draft, retained but superseded by this Mermaid source.

## Logical workflow

```mermaid
flowchart LR
  B[Authenticated browser]
  API[FastAPI API]
  N[Nginx and React on public EC2]
  S3[(Private S3: latest successful PDF per user)]
  DB[(Private RDS PostgreSQL and planned pgvector)]
  EQ[[SQS extraction queue]]
  EDQ[[Extraction DLQ]]
  X[PDF extraction and cleanup process]
  V[[SQS embedding queue]]
  VDQ[[Embedding DLQ]]
  E[MiniLM CPU embedding process]

  B -->|HTTPS submit, poll, browse, review, save| N
  N --> API
  API -->|Upload; preserve prior PDF until success| S3
  API -->|Durable task and draft state| DB
  API -->|Publish extraction task after safe acceptance| EQ
  API -->|202 task status; owner-scoped polling| B
  EQ -->|Poll and deliver extraction task| X
  X -->|Read submitted PDF| S3
  X -->|Draft and extraction status| DB
  EQ -->|Redrive after maxReceiveCount TBD| EDQ
  B -->|Human review, edit, explicit save| API
  API -->|Idempotent save and embedding task| V
  V -->|Poll and deliver embedding task| E
  E -->|Read approved revision metadata| DB
  E -->|Persist approved profile and vectors| DB
  V -->|Redrive after maxReceiveCount TBD| VDQ
  B -->|View recommendations| API
  API -->|Query persisted vectors and jobs| DB
  DB -->|Matching results| API
```

The API must make task state and queue publication safely recoverable before returning durable acceptance. The specific consistency mechanism is unresolved. Extraction produces a reviewable draft; embeddings are queued only after explicit user save. Queue parameter values and cleanup interval are unresolved.

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
  API -->|Logical publish; HTTPS transport via IGW| Q1
  API -->|Logical publish after save; HTTPS transport via IGW| Q2
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

**Edge key:** labels identify logical workflow and transport paths. S3 and SQS are regional AWS services outside the VPC. The public API publishes to SQS through the internet gateway. The private worker polls SQS public endpoints through the provisional NAT gateway; S3 reads and writes use the separate S3 gateway endpoint. SQS redrives a message to its DLQ after the still-undecided `maxReceiveCount`; workers do not publish directly to DLQs. ECR access path, exact endpoint/security rules, and deployment-time image-pull design remain to be finalized.

RDS is planned Single-AZ. Its subnet group covers a second Availability Zone for placement; there is no standby database or HA claim. Learner Lab's supplied `LabRole` does not support a claim of custom per-component least-privilege roles. Enhanced Monitoring is unavailable in the lab; standard monitoring and CloudWatch logs/metrics are the current plan, with alarms still TBD.
