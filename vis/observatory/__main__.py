"""Enable ``python -m vis.observatory`` CLI execution."""

import sys

from vis.observatory.cli import main

# Propagate the CLI result as the process exit status: 0 success, 1 expected
# user error, 2 usage (argparse raises SystemExit(2) itself).
sys.exit(main())
