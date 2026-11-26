"""Unit tests for the Avro seam: the missing-library stop, Output.avro with a stand-in writer, and a real round trip
when fastavro is installed (skipped otherwise)."""
import io
import tempfile
import unittest
from pathlib import Path

from retailgen import avro
from retailgen.avro import FASTAVRO_PIN, MissingAvroWriter, MissingDependency
from retailgen.manifest import Manifest
from retailgen.writers import Output

SCHEMA = {"type": "record", "name": "Example", "fields": [{"name": "id", "type": "string"},
                                                          {"name": "n", "type": ["null", "long"]}]}


class RecordingWriter:
    """Returns fixed bytes and remembers what it was asked to write."""

    def __init__(self):
        self.calls = []

    def to_bytes(self, schema, records):
        self.calls.append((schema, list(records)))
        return b"0123456789"


class SeamTest(unittest.TestCase):

    def test_missing_library_stops_with_the_pin_in_the_message(self):
        with self.assertRaises(MissingDependency) as caught:
            MissingAvroWriter().to_bytes(SCHEMA, [])
        self.assertIn(FASTAVRO_PIN, str(caught.exception))

    def test_output_writes_the_writers_bytes_and_notes_the_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer, man = RecordingWriter(), Manifest()
            out = Output(Path(tmp), man, avro_writer=writer)
            rel = out.avro([{"id": "a", "n": 1}, {"id": "b", "n": None}], SCHEMA, None, "braze", "sends", "s.avro")
            self.assertEqual((Path(tmp) / rel).read_bytes(), b"0123456789")
            self.assertEqual(man.files[rel]["rows"], 2)
            self.assertEqual(writer.calls[0][0], SCHEMA)

    def test_keep_share_cuts_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Output(Path(tmp), Manifest(), avro_writer=RecordingWriter())
            rel = out.avro([{"id": "a", "n": 1}], SCHEMA, None, "braze", "sends", "s.avro", keep_share=0.4)
            self.assertEqual((Path(tmp) / rel).read_bytes(), b"0123")


@unittest.skipUnless(avro.available(), f"{FASTAVRO_PIN} is not installed here; the Avro round trip is not verified")
class RoundTripTest(unittest.TestCase):

    def test_records_read_back_the_same(self):
        import fastavro
        records = [{"id": "a", "n": 1}, {"id": "b", "n": None}]
        data = avro.default_writer().to_bytes(SCHEMA, records)
        self.assertEqual(list(fastavro.reader(io.BytesIO(data))), records)


if __name__ == "__main__":
    unittest.main()
