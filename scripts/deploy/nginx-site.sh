#!/usr/bin/env bash
# ============================================================
# 프로젝트명: Common Agent
# 스크립트:  Nginx 리버스 프록시 설정 생성
# 사용법:    sudo ./scripts/deploy/nginx-site.sh agent.example.com
# 작성:      deploy-scripts-builder (자동 생성)
# ============================================================
# 앱은 Host 헤더가 .env 의 APP_TRUSTED_ORIGINS 호스트와 정확히 같아야 요청을 받는다.
# 그래서 proxy_set_header Host $http_host 가 필수다. HTTPS 인증서는 certbot 으로 따로 붙인다.
set -euo pipefail
trap 'echo -e "\033[0;31m❌ 오류 발생! 라인 $LINENO\033[0m" >&2; exit 1' ERR

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
DOMAIN="${1:-}"
[ -n "$DOMAIN" ] || { echo -e "${RED}사용법: sudo $0 <도메인>${NC}"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo -e "${RED}❌ sudo 로 실행하세요${NC}"; exit 1; }
CONF="/etc/nginx/sites-available/common-agent"

cat > "$CONF" <<NGINX_EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8770;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # 연구 요청은 몇 분 걸릴 수 있다
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }
}
NGINX_EOF

ln -sf "$CONF" /etc/nginx/sites-enabled/common-agent
nginx -t
systemctl reload nginx
echo -e "${GREEN}✅ Nginx 설정 완료: $DOMAIN → 127.0.0.1:8770${NC}"
echo -e "${YELLOW}   다음 단계: .env 에 APP_TRUSTED_ORIGINS=https://$DOMAIN 과 APP_ACCESS_TOKEN=<긴 비밀번호> 를 넣고${NC}"
echo -e "${YELLOW}   sudo systemctl restart common-agent, 그리고 certbot --nginx -d $DOMAIN 으로 HTTPS 를 붙이세요.${NC}"
