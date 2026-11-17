# pusher

Uploads the generator's `landing_staging/` files to a Databricks volume, server to server, as real source systems would
deliver them. It is a use case of the generator's output: it depends only on the `landing_staging/` layout, lives
outside the `retailgen` library, and never reads the answer key.

Each file goes to `/Volumes/workspace/retail/raw/landing/<source>/<entity>/<file>` with the Databricks Files API.
Standard library only.

## Run interface

| Item | Value |
|---|---|
| Command | `python -m pusher history` or `python -m pusher day YYYY-MM-DD` (the image's entrypoint is `python -m pusher`) |
| Modes | `history`: every file under `landing_staging/history/`. `day YYYY-MM-DD`: every file under `landing_staging/increments/day=<date>/`. The date is always given; there is no "yesterday" |
| Input | `landing_staging/` mounted read-only at `/data/landing_staging`. Nothing else is mounted |
| Environment | `DATABRICKS_HOST` (an `https://` host, nothing after it), `DATABRICKS_TOKEN`. Optional: `PUSH_DRY_RUN=1` lists the files without sending and needs neither of the first two; `PUSH_LANDING_ROOT` overrides the mount path (for local runs) |
| Exit codes | `0` every file sent or skipped; `1` some files failed (the others were still sent); `2` bad configuration or input (unknown mode, bad date, missing folder or credentials) |
| Log | stdout only, one line per file: `PUSH <source>/<entity>/<file> size=<bytes> status=<204, skipped, dry-run or failed> delivery=<history or increment day=D>`, then `DONE sent=<n> skipped=<n> failed=<n>`. Bad input prints one `ERROR <reason>` line. The token and response bodies are never logged |
| Run model | one-shot: the container does one push and exits. No ports, no state, nothing written (a read-only root filesystem works) |
| Network | outbound HTTPS to the Databricks host only |
| User | non-root, uid 10001 |

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
| `mode.py` | Parse `history` or `day YYYY-MM-DD` |
| `config.py` | Read and validate the environment |
| `planner.py` | List the files of one delivery from the layout |
| `volume_client.py` | The `VolumeClient` interface and the Files API client |
| `pusher.py` | Skip or upload each file and count the results |
| `send_log.py` | Write the log lines |
| `cli.py`, `__main__.py` | Wire the parts together and return the exit code |
