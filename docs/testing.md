# Testing the generator

Run every test from the repo root with one command:

    python -m unittest

It uses Python's built-in `unittest`, so nothing needs installing. The whole run takes about two minutes, almost
all of it spent generating small datasets.

## What the tests cover

| File | What it proves |
|---|---|
| `tests/test_manifest_guards.py` | The three guards that keep the defect catalogue and the code in step: planting an undeclared defect raises `KeyError`; filling a description with the wrong placeholder names raises `ValueError`; a declared defect that nothing planted shows up in `unrecorded()`, which is what makes `generate.py` exit non-zero. It also checks that repeated records add up. |
| `tests/test_determinism.py` | Two runs with the same seed and scale write byte-identical files. This is the safety net for refactoring the generator: change the code, rerun, and a difference means the data changed. |
| `tests/test_validate_truncated.py` | `validate.py` prints a FAIL line, and does not crash, when a gzip or Parquet file is cut short. It arrives with the #437 fix branch (`fix/validate-truncated-file`), so it is present only once that branch is merged. |

## How the guard tests stay away from the answer key

`Manifest` takes its catalogue as a constructor argument (`Manifest(registry=...)`) and defaults to the real one.
The guard tests pass a two-entry fake catalogue, so they never read the real defects. The determinism test compares
`landing_staging/` only and runs with `--no-truth`. No test opens `answer_key/` or prints a defect.

## Reading a failure

- A guard test failing means the catalogue rules changed.
- The determinism test failing means a change altered the output: either it was meant to (then update nothing, just
  know the data changed) or an extra random draw crept in (see "Known design weaknesses" in the walkthrough).
- The truncated-file test failing with a traceback means a new read in `validate.py` isn't going through the
  `read_gz`, `read_text` or `read_parquet` helpers.
