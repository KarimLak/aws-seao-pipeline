import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
 
import boto3
 
RECHERCHE_URL = "https://api.seao.gouv.qc.ca/prod/api/recherche"
DETAIL_URL_TEMPLATE = "https://api.seao.gouv.qc.ca/prod/api/avis/{uuid}/consulter"
HEADERS = {"Accept": "application/json", "User-Agent": "seao-elt/1.0"}
 
RAW_BUCKET = os.environ["RAW_BUCKET"]
EXTRACTED_TABLE = os.environ.get("EXTRACTED_TABLE", "seao-extracted-contracts")
 
s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")
 
 
def http_get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
 
 
def list_today(day: str) -> list:
    url = f"{RECHERCHE_URL}?{urllib.parse.urlencode({'statIds': 6})}"
    results = http_get_json(url).get("apiData", {}).get("results", [])
    return [n for n in results if (n.get("datePublicationUtc") or "")[:10] == day]
 
 
def already_extracted(uuid: str) -> bool:
    """Return True if this uuid is already in the extracted-contracts table."""
    resp = ddb.get_item(
        TableName=EXTRACTED_TABLE,
        Key={"uuid": {"S": uuid}},
    )
    return "Item" in resp
 
 
def mark_extracted(uuid: str, process_date: str) -> None:
    """Record that we've successfully written this contract to S3."""
    ddb.put_item(
        TableName=EXTRACTED_TABLE,
        Item={
            "uuid": {"S": uuid},
            "process_date": {"S": process_date},
            "extracted_at": {"S": datetime.now(timezone.utc).isoformat()},
        },
    )
 
 
def lambda_handler(event, context):
    day = (event or {}).get("process_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notices = list_today(day)
    print(f"{len(notices)} notices published on {day}")
 
    written = 0
    skipped = 0
    failed = 0
 
    for i, n in enumerate(notices, 1):
        uuid = n.get("uuid")
        if not uuid:
            continue
 
        # Skip if we've already extracted this contract in any previous run.
        if already_extracted(uuid):
            skipped += 1
            continue
 
        # Fetch and write the contract.
        try:
            detail = http_get_json(DETAIL_URL_TEMPLATE.format(uuid=uuid)).get("apiData")
        except Exception as e:
            print(f"  ! fetch failed for {uuid}: {e}")
            failed += 1
            continue
 
        record = {"uuid": uuid, "contract": detail}
        key = f"raw/dt={day}/{uuid}.json"
        try:
            s3.put_object(
                Bucket=RAW_BUCKET,
                Key=key,
                Body=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as e:
            print(f"  ! s3 put failed for {uuid}: {e}")
            failed += 1
            continue
 
        # Mark in DynamoDB ONLY after the S3 write succeeded — if the put
        # fails halfway, a retry will reprocess this uuid instead of skipping.
        mark_extracted(uuid, day)
 
        written += 1
        print(f"  + ({i}/{len(notices)}) {key}")
        time.sleep(0.3)
 
    print(
        f"Done. new={written}  skipped(already extracted)={skipped}  failed={failed}  "
        f"location=s3://{RAW_BUCKET}/raw/dt={day}/"
    )
    return {
        "process_date": day,
        "new": written,
        "skipped": skipped,
        "failed": failed,
        "prefix": f"raw/dt={day}/",
    }