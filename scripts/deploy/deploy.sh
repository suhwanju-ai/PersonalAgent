#!/usr/bin/env bash
# ============================================================
# 프로젝트명: Common Agent
# 스크립트:  배포 (git pull → 문법 점검 → 서비스 재시작)
# 사용법:    ./scripts/deploy/deploy.sh   (재시작에 sudo 필요)
# 작성:      deploy-scripts-builder (자동 생성)
# ============================================================
set -euo pipefail
trap 'echo -e "\033[0;31m❌ 오류 발생! 라인 $LINENO\033[0m" >&2; exit 1' ERR

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo -e "${CYAN}[1/4] 작업 트리 확인...${NC}"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
  || { echo -e "${RED}  ❌ 커밋되지 않은 변경이 있습니다. 정리 후 다시 실행하세요${NC}"; exit 1; }
PREV="$(git rev-parse --short HEAD)"

echo -e "${CYAN}[2/4] 최신 코드 가져오기...${NC}"
git pull --ff-only

echo -e "${CYAN}[3/4] 문법 점검...${NC}"
if ! python3 -m compileall -q app.py lab agents; then
  echo -e "${RED}  ❌ 문법 오류. 이전 커밋($PREV)으로 되돌리려면: git reset --hard $PREV${NC}"; exit 1
fi

echo -e "${CYAN}[4/4] 서비스 재시작...${NC}"
sudo systemctl restart common-agent
sleep 2
if systemctl is-active --quiet common-agent; then
  echo -e "${GREEN}✅ 배포 완료 ($PREV → $(git rev-parse --short HEAD))${NC}"
else
  echo -e "${RED}❌ 서비스가 올라오지 않았습니다: journalctl -u common-agent -n 50${NC}"; exit 1
fi
