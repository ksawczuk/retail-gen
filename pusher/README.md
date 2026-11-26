# pusher

Uploads the generator's `landing_staging/` files to a Databricks volume, server to server, as real source systems would
deliver them. It is a use case of the generator's output: it depends only on the `landing_staging/` layout, lives
outside the `retailgen` library, and never reads the answer key.

Each file goes to `/Volumes/workspace/retail/raw/landing/<source>/<entity>/<file>` with the Databricks Files API.
Standard library only.

## Run interface

| Item | Value |
|---|---|
| Command | `python -m pusher history`, `python -m pusher day YYYY-MM-DD`, `python -m pusher next --state FILE` or `python -m pusher unmark YYYY-MM-DD --state FILE` (the image's entrypoint is `python -m pusher`) |
| Modes | `history`: every file under `landing_staging/history/`. `day YYYY-MM-DD`: every file under `landing_staging/increments/day=<date>/`. `next` and `unmark`: the daily feed, below. The date is always given or kept in the state file; there is no "yesterday" |
| Input | `landing_staging/` mounted read-only at `/data/landing_staging`. `next` and `unmark` also need the state file's folder, read-write (below) |
| Environment | `DATABRICKS_HOST` (an `https://` host, nothing after it), `DATABRICKS_TOKEN`. Optional: `PUSH_DRY_RUN=1` lists the files without sending and needs neither of the first two; `PUSH_LANDING_ROOT` overrides the mount path (for local runs); `HTTPS_PROXY` (below). `unmark` needs only `PUSH_LANDING_ROOT` (or the mount) |
| Exit codes | `0` done; `1` some files failed (the others were still sent); `2` bad configuration or input. Every line and its exit code: [Output lines](#output-lines) |
| Log | stdout only; [Output lines](#output-lines). The token and response bodies are never logged |
| Run model | one-shot: the container does one run and exits. No ports. `history` and `day` write nothing (a read-only root filesystem works); `next` and `unmark` write only the state file and its lock |
| Network | outbound HTTPS to the Databricks host only: direct, or through the forward proxy named by `HTTPS_PROXY` |
| User | non-root, uid 10001 |

### Output lines

| Line | When | Exit code |
|---|---|---|
| `PUSH <source>/<entity>/<file> size=<bytes> status=<204, skipped or dry-run> delivery=<history or increment day=D>` | One per file sent, skipped (same size already in the volume) or listed in a dry run | (the run's) |
| `PUSH ... status=failed delivery=... error=<short reason>` | One per file that failed; the other files still go | `1` |
| `DONE sent=<n> skipped=<n> failed=<n>` | End of every push | `0`, or `1` if `failed` is above 0 |
| `NEXT day=D` | `next` found D as the earliest day not yet pushed; the `PUSH` and `DONE` lines follow | (the run's) |
| `RECORDED day=D` | `next` pushed D with no failed file and wrote it to the state | `0` |
| `NOT RECORDED day=D reason=failed_files` | `next` had failed files; D stays unpushed, so the next run pushes it again | `1` |
| `NOT RECORDED day=D reason=dry_run` | `next` in a dry run; nothing is recorded | `0` |
| `ALL PUSHED last=D` | `next` found every increment day already pushed; nothing is sent | `0` |
| `UNMARKED day=D` | `unmark` removed D from the state | `0` |
| `ERROR <reason>` | Bad input; nothing was sent and the state is unchanged | `2` |

### The daily feed: `next`, `unmark` and the state file

| Item | Value |
|---|---|
| `next --state FILE` | Pushes the earliest increment day not in the state, exactly as `day` does, then records it if no file failed. The increment days are the `increments/day=YYYY-MM-DD` folders under the landing root, so the last day follows the data |
| `unmark YYYY-MM-DD --state FILE` | Removes that day from the state, so the next `next` pushes it again. Only the newest pushed day can be removed, so the pushed days stay an unbroken run from the first one. It never pushes, never builds a client and never deletes anything from the volume |
| State file | Plain text, one `YYYY-MM-DD` per line, oldest first (`cat` shows what has been pushed). Written through a temporary file and a rename, so a crash leaves the old or the new state, never half of one. A missing file means nothing has been pushed. A missing folder, or a file that is not an unbroken run of increment days, is exit `2` |
| Where it lives | Given by `--state`; there is no default. It must be outside `landing_staging/` and not under a folder named `answer_key` or `out` (exit `2` otherwise). In the container, mount its folder read-write, owned by uid 10001; the root filesystem can stay read-only |
| Lock | `next` and `unmark` hold `FILE.lock` (beside the state file) while they run. A second run that finds it exits `2` with `ERROR another pusher run holds <name>.lock; ...`, so the timer and a manual run cannot overlap. The lock is removed when the run ends, even after failed files. If a run was killed and left the lock behind, and no pusher is running, remove the lock file by hand |
| `day D` by hand | Does not touch the state. If `day D` is pushed by hand, a later `next` pushes D again; files already in the volume with the same size are skipped |

#### Recovery: a day was pushed after the day before it failed to load

Example: the load of 2026-10-05 failed and the service was disabled, but the timer had already pushed 2026-10-06. The
state ends with `2026-10-06`. Below, `/state/pushed_days.txt` stands for wherever the state file is mounted.

1. Remove 2026-10-06's files from the volume (the `it-infra` runbook has the command for the Files API).
2. Take 2026-10-06 out of the state:

```bash
docker compose -f pusher/compose.yaml run --rm retail-gen-pusher unmark 2026-10-06 --state /state/pushed_days.txt
```

   Success: `UNMARKED day=2026-10-06`. If more than one later day was pushed, unmark each one, newest first; an older
   day first gives `ERROR 2026-10-06 is not the newest pushed day; unmark 2026-10-07 first`.
3. Once 2026-10-05 is loaded, enable the service again. The next timer run (or a manual run once the service is
   disabled) pushes 2026-10-06:

```bash
docker compose -f pusher/compose.yaml run --rm retail-gen-pusher next --state /state/pushed_days.txt
```

   Success: `NEXT day=2026-10-06`, the `PUSH` lines, `DONE ... failed=0` and `RECORDED day=2026-10-06`.

### Egress proxy (`HTTPS_PROXY`)

| Item | Value |
|---|---|
| Unset or empty | the pusher connects straight to the Databricks host |
| `http://host:port` | the pusher connects to the proxy, which tunnels to the Databricks host on port 443 (`CONNECT`); TLS to Databricks runs inside the tunnel, and the certificate is checked against the Databricks host name. On datapig compose sets `HTTPS_PROXY=http://pusher-proxy:3128` under `environment:`, not in `.env` |
| Any other value | exit code `2` with `ERROR HTTPS_PROXY must be http://host:port`, nothing sent, also in a dry run. An `https://` proxy, a missing port, credentials, a path or a query are all refused |
| Ignored | `https_proxy` (lower case) and `NO_PROXY` |
| Proxy refuses the tunnel | the file is logged `status=failed error=PUT_proxy_refused_the_tunnel:_HTTP_<status>` (for example 403) and the other files still go; exit code `1`. Only the status number is logged, never the proxy's text, its address or the token |

A connection error or a refused tunnel fails the file at once; only HTTP 429, 500, 502, 503 and 504 are retried.

A file already in the volume with the same size is skipped; a file of a different size is overwritten. `COPY INTO` in
bronze identifies files by path and never reloads one it has loaded, so if the data is regenerated with different
contents, clear the volume's landing folders first.

## Build and run

```bash
docker build -t retail-gen-pusher pusher/
```

A dry run needs no credentials:

```bash
docker run --rm -e PUSH_DRY_RUN=1 -v "$PWD/out/landing_staging:/data/landing_staging:ro" retail-gen-pusher history
```

### Base image

The `FROM` line in `Dockerfile` pins `python:3.12.8-slim-bookworm` to the digest of its multi-arch index
(`sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0`, taken 2026-11-18), so a re-tag of the
version cannot change what is built. To refresh it:

```bash
docker buildx imagetools inspect python:3.12.8-slim-bookworm
```

Success: the output starts with `Name:` and a `Digest: sha256:...` line. Put that index digest (not a platform
manifest's) after `@` in the `FROM` line, update the date above, rebuild, and run the tests.

For a real run, copy `.env.example` to `.env` and fill it in, then use the example `compose.yaml` (IT owns the real setup
on datapig):

```bash
LANDING_STAGING_DIR="$PWD/out/landing_staging" docker compose -f pusher/compose.yaml run --rm retail-gen-pusher day 2026-10-01
```

## Tests

```bash
python -m unittest discover -s pusher -t .
```

They use a fake volume client and fake HTTP connections: no network, no Docker.

## Code

| File | One job |
|---|---|
| `commands.py` | Parse the command line into one command (`history`/`day`, `next`, `unmark`) and run it |
| `mode.py` | Parse `history` or `day YYYY-MM-DD` |
| `push_state.py` | Read, check and write the pushed days; the lock beside the state file |
| `config.py` | Read and validate the environment |
| `planner.py` | List the files of one delivery, and the increment days, from the layout |
| `connectors.py` | How a connection to Databricks is opened: direct, or through the proxy tunnel |
| `volume_client.py` | The `VolumeClient` interface and the Files API client |
| `pusher.py` | Skip or upload each file and count the results |
| `send_log.py` | Write the log lines |
| `cli.py`, `__main__.py` | Run the command and return the exit code; bad input becomes exit `2` |
