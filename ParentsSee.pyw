"""Запуск ParentsSee без окна консоли.

  двойной клик         -> включить защиту (трей) и открыть окно
  ParentsSee.pyw agent -> только фоновая защита
  ParentsSee.pyw settings -> только окно настроек
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parentssee.__main__ import main

raise SystemExit(main())
