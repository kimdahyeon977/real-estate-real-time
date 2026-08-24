# realty-watch

네이버부동산·당근부동산에 새 매물이 뜨면 Discord로 알려주는 감시 봇.

매물이 팔리기 전에 먼저 연락하는 게 목적이라, 발견에서 알림까지의 지연을 줄이는 데 집중했다.
자동 계약은 본인확인·전자서명·계약금 이체가 필요해 봇이 대신할 수 없다. 알림까지가 범위다.

## 동작

- **네이버**: `fin.land.naver.com` 공개 엔드포인트로 단지별 매물 조회
  - 매 사이클 단지별 **매물 수만** 확인(요청 1건/단지)하고, 수가 바뀐 단지만 전량 조회
  - 매물 수가 그대로여도 15분마다 강제로 다시 읽는다 — 가격 인하는 매물 수를 바꾸지 않기 때문
- **당근**: 동 지도 페이지의 schema.org JSON-LD(`#dong-articles`)를 파싱. 단독주택·빌라 직거래는 여기서만 잡힌다
- 신규 매물과 가격 변동을 나눠서 알림
- 첫 실행은 기준선만 저장하고 알리지 않는다(`cold_start_silent`) — 안 그러면 기존 매물 수백 건이 한꺼번에 날아온다

## 설치

```bash
git clone <this repo> && cd realty-watch
pip install -r requirements.txt
cp config.example.yaml config.yaml     # config.yaml은 gitignore 대상
```

`config.yaml`의 `discord_webhook`을 채운다. Discord에서 채널 편집 → 연동 → 웹후크 → 새 웹후크로 발급한다.

> `curl_cffi`는 선택이 아니라 필수다. 네이버는 평범한 `requests` TLS 지문에 HTTP 429를 돌려주고,
> 브라우저 지문으로 접근해야 같은 IP에서도 정상 응답한다.

## 실행

```bash
python -m watcher.main --test-notify        # 웹훅 확인
python -m watcher.main --once --dry-run     # 1회만, 알림 없이
python -m watcher.main                      # 상시 감시
```

### 상시 구동 (systemd)

`realty-watch.service`를 `~/.config/systemd/user/`에 두고:

```bash
systemctl --user enable --now realty-watch
loginctl enable-linger "$USER"      # 로그아웃해도 유지
```

프로세스가 죽으면 30초 뒤 자동 재시작된다.

## 설정

```yaml
watches:
  - name: "안양역 1km"
    source: naver
    complex_numbers: [3092, 147880]   # fin.land.naver.com/complexes/<번호> 의 번호
    trade_types: [전세, 월세]
    max_age_days: 3                   # 등록 3일 넘은 매물은 신규로 안 봄
    require_any_of: [탑층, 복층, 단독주택]
    price_rules:
      전세: {price_under: 30000}      # 보증금 3억 미만 (만원 단위)
      월세: {rent_under: 130}         # 월세 130만원 미만

  - name: "인근 당근 직거래"
    source: karrot
    region_paths:
      - "경기도/안양시 만안구/안양동"
```

`cortar_no`(법정동코드)를 주면 그 동의 단지를 모두 순회한다. 단지가 많으면 요청도 늘어나니
특정 단지를 노린다면 `complex_numbers`가 훨씬 가볍다.

## 알려진 한계

- **탑층 판별이 완전하지 않다.** 네이버는 층을 `고/36`처럼 뭉개서 주는 경우가 많아, 층이 숫자로
  올 때만 확실히 판별된다. 나머지는 매물 설명에 "탑층/팬트하우스" 같은 표현이 있을 때만 잡힌다.
- **네이버에서 단독주택은 조회되지 않는다.** 단지 기반 API라 단지가 없는 매물은 목록에 없다.
  법정동 단위 매물 API(`article/legalDivisionArticleList`)는 요청 스키마를 확인하지 못했다.
  단독주택은 당근 쪽에서 커버한다.
- **당근은 동당 최신 20건만 노출된다.** 매물이 빠르게 올라오는 지역이면 그 밖으로 밀려난 건 놓친다.
- 네이버는 출처 IP 단위로 레이트리밋이 걸린다. 데이터센터 IP에서는 `new.land.naver.com`이 429로
  고정되는 것을 확인했다. 가정용 회선에서는 여유가 있다.

공개 API가 아닌 경로를 쓰므로 개인 용도의 저빈도 조회를 전제로 한다. 폴링 주기 하한은 30초다.
