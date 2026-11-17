"""The run log: one stdout line per file and a closing summary line. It never takes a token."""


class SendLog:
    """Writes the log lines to an output stream."""

    def __init__(self, out):
        """Keep the stream the lines are written to."""
        self._out = out

    def file_line(self, item, status, delivery, error=None):
        """Write one line for a file: name, size, status and delivery (and a short error if it failed)."""
        line = f"PUSH {item.relative_name} size={item.size} status={status} delivery={delivery}"
        if error:
            line += f" error={error}"
        print(line, file=self._out)

    def summary(self, result):
        """Write the closing line with the counts."""
        print(f"DONE sent={result.sent} skipped={result.skipped} failed={result.failed}", file=self._out)

    def error(self, message):
        """Write a line for a run that could not start."""
        print(f"ERROR {message}", file=self._out)
