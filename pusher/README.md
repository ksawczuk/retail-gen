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
| Environment | `DATABRICKS_HOST` (an `https://` host, nothing after it), `DATABRICKS_TOKEN`. Optional: `PUSH_DRY_RUN=1` lists the files without sending and needs neither of the first two; `PUSH_LANDING_ROOT` overrides the mount path (for local runs); `HTTPS_PROXY` (below) |
| Exit codes | `0` every file sent or skipped; `1` some files failed (the others were still sent); `2` bad configuration or input (unknown mode, bad date, missing folder or credentials) |
| Log | stdout only, one line per file: `PUSH <source>/<entity>/<file> size=<bytes> status=<204, skipped, dry-run or failed> delivery=<history or increment day=D>`, then `DONE sent=<n> skipped=<n> failed=<n>`. Bad input prints one `ERROR <reason>` line. The token and response bodies are never logged |
| Run model | one-shot: the container does one push and exits. No ports, no state, nothing written (a read-only root filesystem works) |
| Network | outbound HTTPS to the Databricks host only: direct, or through the forward proxy named by `HTTPS_PROXY` |
| User | non-root, uid 10001 |

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
| `mode.py` | Parse `history` or `day YYYY-MM-DD` |
| `config.py` | Read and validate the environment |
| `planner.py` | List the files of one delivery from the layout |
| `connectors.py` | How a connection to Databricks is opened: direct, or through the proxy tunnel |
| `volume_client.py` | The `VolumeClient` interface and the Files API client |
| `pusher.py` | Skip or upload each file and count the results |
| `send_log.py` | Write the log lines |
| `cli.py`, `__main__.py` | Wire the parts together and return the exit code |
