#!/usr/bin/env bash
# ============================================================
# 프로젝트명: Common Agent
# 스크립트:  systemd 서비스 등록 (Ubuntu, 리눅스 서버 전용)
# 사용법:    sudo ./scripts/deploy/install-service.sh [실행 사용자]
# 작성:      deploy-scripts-builder (자동 생성)
# ============================================================
set -euo pipefail
trap 'echo -e "\033[0;31m❌ 오류 발생! 라인 $LINENO\033[0m" >&2; exit 1' ERR

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_USER="${1:-${SUDO_USER:-root}}"
UNIT=/etc/systemd/system/common-agent.service

[ "$(id -u)" -eq 0 ] || { echo -e "${RED}❌ sudo 로 실행하세요${NC}"; exit 1; }
[ -f "$ROOT/.env" ] || { echo -e "${RED}❌ $ROOT/.env 가 없습니다. .env.example 을 복사해 채우세요${NC}"; exit 1; }
PY="$(command -v python3)" || { echo -e "${RED}❌ python3 가 없습니다${NC}"; exit 1; }

cat > "$UNIT" <<UNIT_EOF
[Unit]
Description=Common Agent
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$ROOT
Environment=PYTHONUTF8=1
ExecStart=$PY -u $ROOT/app.py
Restart=on-failure
RestartSec=3
# 연구원 자식 프로세스(8771/8772)까지 함께 종료한다
KillMode=control-group

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable --now common-agent
echo -e "${GREEN}✅ common-agent 서비스 등록·시작 완료 (사용자: $RUN_USER)${NC}"
echo -e "${YELLOW}   로그: journalctl -u common-agent -f${NC}"
