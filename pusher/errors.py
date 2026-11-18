"""The error raised for bad configuration or input; the command line turns it into exit code 2."""


class InputError(Exception):
    """Bad mode, bad date, bad environment or an unusable landing folder; its message is safe to print."""
