"""Convenient checkout-local installation entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eds.cli import main

raise SystemExit(main(["install-skills", *sys.argv[1:]]))
