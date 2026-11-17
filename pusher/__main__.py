"""Entry point for `python -m pusher`: passes the command line, environment and stdout to the CLI."""

import os
import sys

from pusher.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ, sys.stdout))
