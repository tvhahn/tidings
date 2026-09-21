* Build docker image (from the docker/email_parsing directory):
```bash
docker build --platform linux/amd64 -t docker-image:test .
```

* Run docker image as a container:
```bash
docker run -it --rm docker-image:test
```

    ... or run the conatiner with an assigned name:
```bash
docker run --name lambda-func -d docker-image:test
# -d is for detached mode
```

* Start a stopped container:
```bash
docker start <container_id>
```

* Open up running container in another terminal:
```bash
docker exec -it <container_id> /bin/bash
```

## Deploy scripts

Numbered, run in order for a first deployment; the full walkthrough is
[`docs/guides/aws-deployment.md`](../../docs/guides/aws-deployment.md). The four
that carry behaviour worth knowing:

* `4_establish_lambda_func.sh` — creates `email-parser` at 256 MB / 60 s and
  attaches the `email-parser-dlq` SQS queue as its on-failure destination.
* `5_update_func.sh` — rolls the pushed `:latest` onto both `email-parser` and
  `monthly-summary`, waits for each update, and prints the resolved image
  digests (`:latest` moves, the digest does not).
* `6_invoke_func.sh` — post-deploy boot check, side-effect free. Invokes with
  `test_event.json`, which names a bucket that does not exist: the handler logs
  `Categorization model=<model> reasoning_effort=<effort>` and then dies at the
  S3 read, so a `FunctionError` is expected and no DB write, notification, or
  model call happens. Exits 0 only if that log line was found.
* `11_set_function_env.sh` — merge-safe setter for the personal-config env vars
  (`CATEGORIZATION_MODEL`, `CATEGORIZATION_REASONING_EFFORT`,
  `NOTIFICATION_BLOCKED_COMPANIES`, `USER_MAPPINGS`). Use it instead of
  `aws lambda update-function-configuration --environment`, which replaces the
  whole variable map. `--set KEY=VALUE`, `--set-file KEY=PATH` (keeps personal
  values out of the shell history), `--unset KEY`, `--function NAME`,
  `--dry-run`; `-h` for the full text.
