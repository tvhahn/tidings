# S3 backup of attachments and statements

Mirror your receipt attachments and statement PDFs to an S3 bucket you own, so the
one part of `data/` the backup zip cannot carry has a durable copy.

:::note[Prerequisites]
This section only appears in Settings → Backup when AWS credentials are already
present on the machine — environment variables, a `~/.aws` profile, or an IAM role.
Detection uses the standard boto3 chain. If you have no AWS credentials, the S3
backup section stays hidden and the [backup zip](backup-and-restore.md) is your
backup path.

You bring your own bucket. Tidings never creates one, and it never touches AWS
credentials — it only reads whatever is already configured.
:::

**For self-hosters who already use AWS and want a durable copy of their uploaded
files.** The backup zip from Settings → Backup carries every transaction and your
configuration, but it deliberately leaves out the receipt and statement *files* —
those live only in `data/raw/`. This feature is the durability answer for those
files. It works on either storage backend (SQLite or DynamoDB).

## What it backs up

Two stores, mirrored to your bucket:

- **Receipt and document attachments** — `data/raw/attachments/`.
- **Statement PDFs** — `data/raw/statements/`.

Alongside the files, every successful sync uploads a `manifest.json`: a metadata
snapshot of the attachment rows (including which transaction each is linked to and
any parse results) and the statement rows (including the reconciled transaction
list for each statement). The manifest is what lets a restore rebuild the links,
not just the raw files.

The bucket layout is:

```text
<prefix>/attachments/<YYYY-MM>/<file>
<prefix>/statements/<Institution>/<file>
<prefix>/manifest.json
```

`<prefix>` is the optional key prefix you configure; without one, the three names
sit at the bucket root. The backup only ever reads, writes, or deletes keys under
those three names. Anything else in the bucket is left alone, so an existing
bucket you already use for other things is safe.

## What it does not do

- **It is not the backup zip.** The zip still does not include attachment or
  statement files — this is the separate durability answer for AWS users. Keep
  taking the zip for transactions and configuration; see
  [backup and restore](backup-and-restore.md).
- **No bucket creation in-app.** You create the bucket yourself (below).
- **No manual "back up now" button.** Sync runs on a schedule, described below.
- **No write-through.** A newly uploaded receipt is mirrored on the next
  scheduled pass, not the instant you attach it.

## Create the bucket

Any region works, but Tidings talks to the bucket in the region it resolves from
`AWS_REGION`, then `AWS_DEFAULT_REGION`, falling back to `us-west-2`. Create the
bucket in that region, or set the environment variable to match wherever you make
it — a region mismatch is the most common verify failure.

### Console

In the AWS S3 console, create a bucket:

- **Name:** globally unique. `tidings-backup-<your-initials>` is a reasonable
  pattern.
- **Region:** the region Tidings resolves (see above).
- **Block public access:** keep all four settings on. Tidings writes with your
  credentials, never via public access.
- **Versioning:** enable it. This is the recommended accidental-delete safety net
  — see [Versioning is your safety net](#versioning-is-your-safety-net) below.
- **Default encryption:** SSE-S3 is fine. SSE-KMS works too; it adds no extra step
  on the Tidings side.

### CLI

The same bucket from the command line, in `us-west-2`:

```bash
aws s3api create-bucket \
  --bucket tidings-backup-example \
  --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2

aws s3api put-public-access-block \
  --bucket tidings-backup-example \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-versioning \
  --bucket tidings-backup-example \
  --versioning-configuration Status=Enabled
```

`us-east-1` is the one region that rejects the `LocationConstraint` argument — drop
the `--create-bucket-configuration` line there.

## Minimal IAM policy

Whatever credentials Tidings resolves need these permissions on the bucket. The
first three are required; the last two are read-only and used only by the Verify
button's warnings. Omitting them degrades those two warnings to
"could not check" — it does not fail verification or sync.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TidingsBackupList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Sid": "TidingsBackupObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::<bucket>/*"
    },
    {
      "Sid": "TidingsBackupVerifyWarnings",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketVersioning",
        "s3:GetBucketPublicAccessBlock"
      ],
      "Resource": "arn:aws:s3:::<bucket>"
    }
  ]
}
```

Replace `<bucket>` with your bucket name in both resource lines.

## Configure and verify

Open **Settings → Backup → S3 backup**:

1. Enter the **bucket** name and, optionally, a **prefix** (a key prefix inside the
   bucket — useful if the bucket holds other things).
2. Choose **Verify**. Tidings checks, in order: AWS credentials are present, the
   bucket exists and is reachable in the resolved region, and a write probe
   succeeds (it puts and then deletes a tiny `<prefix>/.tidings-write-probe`
   object). It also raises non-blocking warnings if S3 Block Public Access is not
   fully on or bucket versioning is not enabled.
3. When verification passes, turn the **enable** toggle on. The first sync runs
   within a minute; after that it runs hourly.

Below the controls, a status row shows the last sync time, the file counts, and the
last error if there was one.

## How sync behaves

- **Hourly reconcile, inside the app process.** No separate service to run. The
  first pass fires within a minute of enabling, then hourly.
- **New and changed files upload.** The reconcile compares what is on disk against
  what is in the bucket and uploads anything new or changed.
- **Deletions are mirrored.** A receipt or statement you delete locally is deleted
  from the bucket on the next pass. This keeps the bucket a faithful mirror rather
  than an ever-growing pile — which is exactly why versioning matters.
- **The manifest refreshes every successful pass**, so the metadata snapshot stays
  current with your files.

### Versioning is your safety net

Because sync mirrors deletions, a file removed locally leaves the bucket on the
next pass. S3 **versioning** is the recommended protection against an accidental
local delete: with versioning on, a delete writes a delete marker and the prior
version is still recoverable in the bucket's version history. Tidings recommends
versioning but never enables or enforces it — that stays your choice on the bucket.
If you skip it, a mirrored deletion is permanent.

### When sync fails

On the first failure in a run of failures, Tidings sends one notification through
your configured notification provider (see [notifications setup](notifications-setup.md)).
It then retries every five minutes until a pass succeeds, at which point it returns
to the hourly cadence. Further failures in the same run stay silent, and recovery is
silent. The current state — last sync, counts, last error — is also on the
status row in Settings → Backup, and over the API at
`GET /api/v1/data/s3-backup-status`.

## Restore

Restore is a command-line step, meant for a fresh or empty install — it downloads
the files and manifest from the bucket and rebuilds the attachment and statement
metadata databases, including the receipt-to-transaction links:

```bash
uv run python -m src.finance.s3_backup_restore --bucket <bucket> --prefix <prefix>
```

`--bucket` and `--prefix` default to the values in `data/config.json` when omitted,
so on the machine that wrote the backup you can usually run it with no arguments.

Preview first with `--dry-run` — it reports what would be downloaded and rebuilt
without writing anything:

```bash
uv run python -m src.finance.s3_backup_restore --bucket <bucket> --dry-run
```

Restore is oriented at a fresh target. Run it against an empty install, confirm the
dry run looks right, then run it for real.

## Troubleshooting

Verify reports the specific failure rather than a generic error:

- **No credentials.** Tidings found no AWS credentials in the standard chain. The
  S3 backup section only shows when credentials are present, so this usually means
  they were removed or an IAM role expired. Confirm your environment,
  `~/.aws/credentials`, or role is in place.
- **Bucket not found.** The bucket name is wrong, or the bucket lives in a
  different AWS account than your credentials. Check the name for typos.
- **Access denied.** The credentials reached the bucket but lack permission. Apply
  the [minimal IAM policy](#minimal-iam-policy) above.
- **Wrong region.** The bucket exists but in a different region than the one
  Tidings resolved (`AWS_REGION`, then `AWS_DEFAULT_REGION`, then `us-west-2`).
  Either recreate the bucket in the resolved region or set the environment variable
  to match the bucket's region.
- **Warnings could not be checked.** If the credentials lack
  `s3:GetBucketVersioning` or `s3:GetBucketPublicAccessBlock`, the two bucket
  warnings show as "could not check" instead of a result. Verification and sync
  still work — add those two read-only permissions if you want the warnings.

Sync failures surface in two places: the status row in Settings → Backup (last
error and last sync time), and the one notification sent on the first failure in a
run of failures through your [notification provider](notifications-setup.md).
