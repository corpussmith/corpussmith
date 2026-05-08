#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Corpus Smith — compatibility shim.

Keeps the historical invocation `python corpussmith.py ...` working while
the real code lives in the `corpussmith/` package. Prefer `python -m corpussmith`
in new scripts.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from corpussmith.app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
