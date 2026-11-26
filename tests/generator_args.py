"""Extra generate.py arguments for the tests that run the whole generator: without the Avro library, leave the
Braze source out so every other source is still generated and checked."""
from retailgen import avro


def source_args():
    """`--skip-source braze` when Avro files cannot be written here, otherwise nothing."""
    return [] if avro.available() else ["--skip-source", "braze"]
