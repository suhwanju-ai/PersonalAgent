# -*- coding: utf-8 -*-
"""실험수행 연구원 — 별도 프로세스로 뜬다.

코드를 짜서 돌리고 수치를 돌려준다. 조사 도구는 이 프로세스에 주어지지 않는다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _serve import serve            # noqa: E402

if __name__ == "__main__":
    serve("experiment")
