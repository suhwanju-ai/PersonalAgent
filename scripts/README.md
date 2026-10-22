# 스크립트 사용 가이드

이 프로젝트는 Python 표준 라이브러리만 쓰므로 **빌드 단계가 없습니다.** 개발 실행과 리눅스 서버 배포 스크립트만 있습니다.
(기존 `run.bat` / `run.sh` 는 그대로 쓸 수 있는 간단한 실행기입니다.)

## 빠른 시작

| 목적 | Linux/Mac | Windows |
|------|-----------|---------|
| 개발 서버 시작 (환경·포트 점검 포함) | `./scripts/dev/start-dev.sh` | `scripts\dev\start-dev.bat` |
| systemd 서비스 등록 (서버) | `sudo ./scripts/deploy/install-service.sh [사용자]` | - |
| 배포 (pull → 점검 → 재시작) | `./scripts/deploy/deploy.sh` | - |
| Nginx 프록시 설정 | `sudo ./scripts/deploy/nginx-site.sh 도메인` | - |

실행 권한: `chmod +x scripts/*/*.sh`

## 외부 공개 시 주의

1. `.env` 에 `APP_TRUSTED_ORIGINS=https://도메인` 과 `APP_ACCESS_TOKEN=<긴 비밀번호>` 를 넣습니다. 토큰이 없으면 외부 접속은 거부됩니다.
2. 앱은 `127.0.0.1` 에만 바인딩됩니다. 같은 서버의 Nginx 뒤에 두고, Nginx 가 `Host` 를 그대로 전달해야 합니다 (`nginx-site.sh` 가 처리).
3. HTTPS 인증서는 `certbot --nginx -d 도메인` 으로 붙입니다.
4. `.env` 는 시작할 때 한 번 읽으므로 고친 뒤에는 `sudo systemctl restart common-agent` 가 필요합니다.
5. 로그: `journalctl -u common-agent -f`
