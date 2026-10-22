#!/usr/bin/env bash
# ============================================================
# 프로젝트명: Common Agent
# 스크립트:  개발 서버 시작 (환경 점검 + 포트 충돌 감지)
# 작성:      deploy-scripts-builder (자동 생성)
# ============================================================
set -euo pipefail
trap 'echo -e "\033[0;31m❌ 오류 발생! 라인 $LINENO\033[0m" >&2; exit 1' ERR

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONUTF8=1

echo -e "${CYAN}[1/3] Python 확인...${NC}"
if command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then PY="$(command -v python)"
else echo -e "${RED}  ❌ Python 3을 찾을 수 없습니다${NC}"; exit 1; fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo -e "${RED}  ❌ Python 3.9 이상이 필요합니다${NC}"; exit 1; }
echo -e "${GREEN}  ✅ $("$PY" --version)${NC}"

echo -e "${CYAN}[2/3] 설정 확인...${NC}"
if [ ! -f ".env" ]; then
  echo -e "${YELLOW}  ⚠️  .env가 없어 .env.example을 복사했습니다. OPENROUTER_API_KEY를 채워 주세요 (Ollama만 쓰면 비워도 됩니다).${NC}"
  cp .env.example .env
fi
echo -e "${GREEN}  ✅ .env OK${NC}"

echo -e "${CYAN}[3/3] 포트 확인 (8770 본체, 8771/8772 연구원)...${NC}"
for port in 8770 8771 8772; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo -e "${RED}  ❌ 포트 $port 가 이미 사용 중입니다. 이전 인스턴스를 먼저 종료하세요.${NC}"; exit 1
  fi
done
echo -e "${GREEN}  ✅ 포트 OK${NC}"

echo -e "${CYAN}http://127.0.0.1:8770/ 에서 열립니다 (Ctrl+C 로 종료)${NC}"
exec "$PY" -u app.py
