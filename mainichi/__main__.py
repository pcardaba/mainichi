"""Allow ``python -m mainichi``."""

from mainichi.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
