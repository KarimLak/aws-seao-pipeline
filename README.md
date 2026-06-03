# SEAO ELT Pipeline

Daily ELT pipeline on AWS that extracts Québec public procurement notices
from SEAO and lands them in a Postgres database queryable by an app.

## Architecture
EventBridge ─► Step Functions ─► Lambda ─► S3 (raw)
│
▼
Glue Crawler ─► Athena (curated Parquet)
│
▼
Lightsail cron ─► Postgres

## How it works
- **Lambda** calls SEAO's public JSON API, dedupes contracts via DynamoDB
  (uuid-keyed), writes one JSON file per contract to S3 partitioned by date.
- **Glue Crawler** catalogs the raw JSON into a Glue table.
- **Athena** SQL flattens the nested structure into a clean `contracts` table
  (Parquet), with `NOT EXISTS` deduplication.
- **Step Functions** orchestrates Lambda → Glue → Athena, retries included.
- **Cron on Lightsail** syncs the Athena output into Postgres for app queries
  (`ON CONFLICT DO UPDATE` for idempotency).
- **EventBridge** fires the whole thing on a daily cron.

## Idempotency
Three independent layers — Lambda (DynamoDB), Athena (`NOT EXISTS`), Postgres
(`ON CONFLICT`) — so the pipeline can run multiple times a day without ever
duplicating data.

## Cost
~$5/month total:
- Lightsail nano instance: $3.50–5
- All AWS pipeline services combined: well under $1

## Files
- `lambda_function.py` — extract Lambda (Python 3.12, stdlib only)
- `seao-elt-pipeline.asl.json` — Step Functions definition (JSONata)
- 
<img width="342" height="790" alt="stepfunctions_graph" src="https://github.com/user-attachments/assets/f0b8efaf-6297-414a-b069-f19011bcc0fb" />

