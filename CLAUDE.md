# CLAUDE.md — naver-search-hub

## Project Overview

**네이버 검색 허브** — FastAPI 기반 네이버 쇼핑/블로그 통합 검색 API 서버.
네이버 오픈 API를 프록시하여 내부에서 활용 가능한 REST API 제공.
Jinja2 HTML 템플릿 포함 (기본 웹 UI).

## Commands

```bash
# 의존성 설치
pip install -r requirements.txt

# 개발 서버
uvicorn main:app --reload --port 8000

# 프로덕션 서버
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Tech Stack

- **Framework**: FastAPI 0.115
- **Server**: Uvicorn
- **Scraping**: BeautifulSoup4 + requests
- **Template**: Jinja2 (웹 UI)
- **Config**: python-dotenv

## Architecture

```
naver-search-hub/
  main.py          # FastAPI 앱 진입점, 라우터 정의
  crawler.py       # 네이버 API/크롤링 로직
  templates/       # Jinja2 HTML 템플릿 (웹 UI)
    index.html     # 검색 UI
  requirements.txt
  __pycache__/
```

## API Endpoints

```
GET /                     # 웹 UI (HTML)
GET /api/shopping?q=검색어  # 쇼핑 검색
GET /api/blog?q=검색어      # 블로그 검색
```

**인증**: 네이버 API 키를 HTTP 헤더로 전달
```
X-Naver-Client-Id: {CLIENT_ID}
X-Naver-Client-Secret: {CLIENT_SECRET}
```

## Environment Variables

```bash
# .env 파일 (선택적)
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret
```

## Conventions

- API 키는 헤더로 받아 처리 — 서버에 저장하지 않음
- `crawler.py` 에 네이버 API 호출 로직 집중
- `main.py` 는 라우터만, 비즈니스 로직 `crawler.py` 로 분리
- Pydantic 모델로 요청/응답 검증

## Known Gotchas

- 네이버 오픈 API 일일 호출 제한 있음 (API 종류별 상이)
- 검색 결과는 네이버 API 응답 그대로 반환 — 정제 로직 주의
- CORS 설정 필요시 `main.py` 에 `CORSMiddleware` 추가

## 컨텍스트 관리

sub-agent를 최대한 활용해서 컨텍스트를 평균 40%, 최대 60%를 넘지 않도록 관리한다.
