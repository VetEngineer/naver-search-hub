# 작업 인계 문서

## 완료된 작업

### 1. KISA 시큐어코딩 보안 취약점 수정 (6f97283)
- [x] XXE 취약점: `xml.etree.ElementTree` → `defusedxml.ElementTree` (crawler.py:7)
- [x] CORS 미들웨어 추가 (ntools.hakhamsolution.co.kr만 허용)
- [x] HTTP 보안 헤더 미들웨어 (X-Frame-Options, X-Content-Type-Options 등)
- [x] 이미지 프록시 `stream=True` + 청크 읽기 (메모리 DoS 방지)
- [x] `defusedxml==0.7.1` 의존성 추가

### 2. 블로그 리뷰 수 추출 정규식 수정 (95b44c5)
- [x] `FsasReviewsResult` typename 앵커 패턴으로 변경
- [x] 5개 업종 15개 업체 전수 검증 완료

### 3. 플레이스 검색 텍스트 파싱 대폭 개선 (f034128)
- [x] 패턴 D: `방문자 리뷰|N|블로그 리뷰|N` 쌍 기반 파싱 (성심당 등)
- [x] 패턴 E: 커머스 키워드(네이버페이/예약/톡톡) 기반 업체명 추출
- [x] 광고 카드 자동 필터링 → placeId 매핑 정확도 향상
- [x] 카드별 텍스트 범위 내 리뷰 수 매칭 (인덱스 기반 대신)
- [x] 대표전화(1588-XXXX) 인식, 의료기관 ID 필터(의/치/약/한), _PLACE_SKIP 확장

### 4. Codex 리뷰 P1/P2 수정 (미커밋)
- [x] **P1** `_fix_pids_by_position` — `pid_pos > name_pos`이면 `continue`로 건너뜀
  - 마지막 카드나 추천/푸터 링크의 무관한 PID가 잘못 할당되던 문제 해결
- [x] **P2** `_FULL_REGION_PREFIX` — bare prefix(`충청|전라|경상`) → 정확한 도 이름으로 변경
  - `충청(?:남도|북도)`, `전라(?:남도|북도)`, `경상(?:남도|북도)`, `제주(?:도|특별자치도)` 등
  - `전라도집`, `경상회관`, `충청칼국수` 등 업체명이 필터되지 않도록 수정
- [x] `_find_addr` 정규식에 전체 도/시 full-form 추가 (서울특별시, 충청남도, 제주특별자치도 등)
  - `_FULL_REGION_PREFIX`와 `_find_addr`의 주소 인식 범위를 동기화

### 5. 배포 설정
- [x] 배포 도메인: ntools.hakhamsolution.co.kr
- [x] DNS: CNAME ntools → cname.vercel-dns.com
- [x] Vercel 대시보드에서 커스텀 도메인 등록 필요 (사용자가 수동 진행 중)

## 다음에 해야 할 작업

### 높은 우선순위
1. **미커밋 변경 커밋 및 배포** — `crawler.py`, `templates/index.html`, `templates/place.html` (204줄 추가 / 28줄 삭제)
2. **Rate Limiting 추가** — `slowapi` 패키지 또는 Vercel/nginx 레벨 설정
3. **인증 추가 검토** — `/api/place/*`, `/api/blog/*` 엔드포인트에 API Key/Bearer Token

### 중간 우선순위
4. **숙박/호텔 업종 지원** — 플레이스 페이지가 별도 렌더링 구조 사용, `_extract_place_script()`에서 미감지
5. **서울 자동차 정비/대전 치과** — 일부 업종에서 방문자 리뷰 수 0으로 반환

### 낮은 우선순위
6. **플레이스 검색 카테고리/주소 추출 개선** — 패턴 E(미용실/맛집)에서 카테고리/주소가 빈값

## 주의사항
- `_fix_pids_by_position`은 이제 이름 앞의 PID만 매칭 — 이름 뒤 마커는 완전 무시
- `_FULL_REGION_PREFIX`와 `_find_addr` 정규식이 동기화되어야 함 (새 도 이름 추가 시 양쪽 수정)
- `crawler.py`의 `_parse_place_cards()` 함수는 5가지 패턴(A→B→D→E→C)을 순차 시도함. 네이버 HTML 구조 변경 시 파싱이 깨질 수 있음
- 네이버 검색 결과는 요청마다 광고 카드가 변동됨 (테스트 시 결과가 달라질 수 있음)
- `_PLACE_SKIP`, `_NAME_DENY` 세트를 수정할 때 기존 업종 검색이 깨지지 않는지 전 업종 테스트 필요

## 관련 파일
- `main.py` — FastAPI 앱, 라우터, CORS/보안 미들웨어
- `crawler.py` — 네이버 API 호출 + 스크래핑 로직 (핵심)
  - `_FULL_REGION_PREFIX` (L619~627) — 전체 도/시 이름 필터 정규식
  - `_find_addr()` (L650~) — 주소 추출 정규식
  - `_fix_pids_by_position()` (L693~) — PID 위치 기반 보정
  - `_parse_place_cards()` (L423~) — 플레이스 검색 결과 파싱 (5패턴)
  - `_parse_one_card()` (L543~) — 개별 카드 텍스트 파싱
- `templates/index.html` — 쇼핑/블로그 검색 UI
- `templates/place.html` — 플레이스 SEO 분석 UI
- `requirements.txt` — defusedxml 추가됨

## 마지막 상태
- 브랜치: main
- 마지막 커밋: f034128 `[fix] 플레이스 검색 텍스트 파싱 대폭 개선`
- 미커밋 변경: `crawler.py`, `templates/index.html`, `templates/place.html`
- 테스트: 수동 Python 검증 통과 (P1 PID 매칭, P2 업체명/주소 필터링, 제주 full-form)
- 배포: Vercel 자동 배포 (main push 시)
