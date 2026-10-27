#!/usr/bin/env python3
"""Entry point for the Output Comment Composer Herdr plugin."""
from occ.ui import log_crash, main


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        log_crash()
        raise
