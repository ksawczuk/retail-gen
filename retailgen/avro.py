"""Writing Avro files: the one place the generator touches the `fastavro` library.

Output.avro calls the writer chosen here; without `fastavro` installed, writing an Avro file stops the run with one
line that names the missing library, and everything else in the generator still works.
"""
import io

FASTAVRO_PIN = "fastavro==1.10.0"


class MissingDependency(RuntimeError):
    """A library the run needs is not installed; the message says which one and how to get it."""


class FastAvroWriter:
    """Writes records with `fastavro`, deflate-compressed, to bytes."""

    def __init__(self, fastavro):
        """Keep the imported fastavro module."""
        self._fastavro = fastavro

    def to_bytes(self, schema, records):
        """Return the Avro object-container bytes for the records under the schema."""
        buffer = io.BytesIO()
        parsed = self._fastavro.parse_schema(schema)
        self._fastavro.writer(buffer, parsed, records, codec="deflate", sync_marker=b"retailgen-sync-1")
        return buffer.getvalue()


class MissingAvroWriter:
    """Stands in when `fastavro` is not installed: any write stops with a clear message."""

    def to_bytes(self, schema, records):
        """Refuse to write, naming the library and its pinned version."""
        raise MissingDependency(f"writing Avro needs {FASTAVRO_PIN}; install it in this environment to generate "
                                "the Braze files")


def default_writer():
    """The fastavro writer when the library imports, otherwise the missing-library stand-in."""
    try:
        import fastavro
    except ImportError:
        return MissingAvroWriter()
    return FastAvroWriter(fastavro)


def available():
    """True when Avro files can be written here."""
    return isinstance(default_writer(), FastAvroWriter)
