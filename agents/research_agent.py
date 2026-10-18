# -*- coding: utf-8 -*-
"""자료조사 연구원 — 별도 프로세스로 뜬다.

무엇이 알려져 있는지 찾는다. 연결된 MCP 서버의 도구와 웹 검색을 쓴다.
코드 실행 도구는 이 프로세스에 아예 주어지지 않는다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _serve import serve            # noqa: E402

if __name__ == "__main__":
    serve("research")
