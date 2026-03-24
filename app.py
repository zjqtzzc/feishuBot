#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口：项目根目录运行，加载 src 服务"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.server import main

if __name__ == "__main__":
    main()
