"""네이버 쇼핑·블로그 통합 검색기 — FastAPI 서버"""

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests as req

from fastapi import FastAPI, Query, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

import crawler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
_EXT_SVC_ERROR = "외부 서비스 오류가 발생했습니다."

app = FastAPI(title="네이버 검색 허브")

TEMPLATES_DIR = Path(__file__).parent / "templates"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/place", response_class=HTMLResponse)
async def place_page():
    return (TEMPLATES_DIR / "place.html").read_text(encoding="utf-8")


@app.get("/api/shopping")
def api_shopping(
    q: str = Query(..., min_length=1, description="검색어"),
    display: int = Query(30, ge=1, le=100),
    sort: str = Query("sim", pattern="^(sim|date|asc|dsc)$"),
    x_naver_client_id: str = Header(..., alias="X-Naver-Client-Id"),
    x_naver_client_secret: str = Header(..., alias="X-Naver-Client-Secret"),
):
    try:
        return crawler.search_shopping(
            q, x_naver_client_id, x_naver_client_secret,
            display=display, sort=sort,
        )
    except Exception as e:
        logger.error("search_shopping error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


@app.get("/api/blog")
def api_blog(
    q: str = Query(..., min_length=1, description="검색어"),
    display: int = Query(20, ge=1, le=100),
    sort: str = Query("sim", pattern="^(sim|date)$"),
    x_naver_client_id: str = Header(..., alias="X-Naver-Client-Id"),
    x_naver_client_secret: str = Header(..., alias="X-Naver-Client-Secret"),
):
    try:
        return crawler.search_blog(
            q, x_naver_client_id, x_naver_client_secret,
            display=display, sort=sort,
        )
    except Exception as e:
        logger.error("search_blog error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


class BlogListRequest(BaseModel):
    urls: list[str]  # 블로그 URL 또는 blogId 목록


class PostContentRequest(BaseModel):
    posts: list[dict]  # [{"blogId": "...", "logNo": "..."}, ...]


MAX_BLOGS = 10
MAX_POSTS_BATCH = 20
DELAY_BLOG_LIST = 1.5   # 블로그 목록 간 딜레이 (초)
DELAY_POST_CONTENT = 2.0  # 본문 크롤링 간 딜레이 (초)


@app.post("/api/blog/list")
def api_blog_list(body: BlogListRequest):
    """다수 블로그의 글 목록 일괄 조회 (RSS 기반)"""
    urls = body.urls[:MAX_BLOGS]
    blog_ids = []
    for url in urls:
        bid = crawler.extract_blog_id_from_url(url)
        if bid:
            blog_ids.append(bid)

    if not blog_ids:
        raise HTTPException(status_code=400, detail="유효한 블로그 URL이 없습니다")

    try:
        return {
            "blogs": crawler.crawl_multiple_blog_lists(blog_ids, delay=DELAY_BLOG_LIST),
            "rateLimit": {
                "delayPerBlog": DELAY_BLOG_LIST,
                "maxBlogs": MAX_BLOGS,
            },
        }
    except Exception as e:
        logger.error("api_blog_list error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


@app.post("/api/blog/batch-content")
def api_blog_batch_content(body: PostContentRequest):
    """선택된 글들의 본문 일괄 크롤링 (밴 방지 딜레이 적용)"""
    posts = body.posts[:MAX_POSTS_BATCH]
    valid_posts = [
        p for p in posts
        if re.match(r'^[a-zA-Z0-9_.\-]+$', str(p.get("blogId", "")))
        and re.match(r'^\d+$', str(p.get("logNo", "")))
    ]
    posts = valid_posts
    if not posts:
        raise HTTPException(status_code=400, detail="유효한 글 정보가 없습니다")

    try:
        return {
            "results": crawler.crawl_posts_content(posts, delay=DELAY_POST_CONTENT),
            "rateLimit": {
                "delayPerPost": DELAY_POST_CONTENT,
                "maxPosts": MAX_POSTS_BATCH,
                "crawled": len(posts),
            },
        }
    except Exception as e:
        logger.error("api_blog_batch_content error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


@app.get("/api/blog/content")
def api_blog_content(
    blogId: str = Query(..., min_length=1, pattern=r"^[a-zA-Z0-9_.\-]+$"),
    logNo: str = Query(..., min_length=1, pattern=r"^\d+$"),
):
    try:
        return crawler.fetch_blog_content(blogId, logNo)
    except Exception as e:
        logger.error("fetch_blog_content error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


# ──────────────────────────────────────────
# 플레이스
# ──────────────────────────────────────────

@app.get("/api/place/search")
def api_place_search(
    q: str = Query(..., min_length=1, max_length=100),
    display: int = Query(5, ge=1, le=20),
):
    """네이버 플레이스 검색 (API 키 불필요)"""
    try:
        return crawler.search_place(q, display=display)
    except Exception as e:
        logger.error("search_place error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


@app.get("/api/place/detail")
def api_place_detail(place_id: str = Query(..., min_length=1, max_length=200)):
    """플레이스 상세 정보 — place_id 또는 플레이스 URL 입력 (API 키 불필요)"""
    pid = crawler.parse_place_id(place_id)
    if not pid:
        raise HTTPException(status_code=422, detail="유효한 플레이스 ID가 아닙니다")
    try:
        place = crawler.fetch_place_by_id(pid)
    except Exception as e:
        logger.error("fetch_place_by_id error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)
    if not place.get("name"):
        raise HTTPException(status_code=404, detail="플레이스 정보를 찾을 수 없습니다")
    return place


@app.get("/api/place/seo")
def api_place_seo(place_id: str = Query(..., min_length=1, max_length=200)):
    """플레이스 SEO/AEO/GEO 분석 — place_id 또는 플레이스 URL 입력 (API 키 불필요)"""
    pid = crawler.parse_place_id(place_id)
    if not pid:
        raise HTTPException(status_code=422, detail="유효한 플레이스 ID가 아닙니다")
    try:
        place = crawler.fetch_place_by_id(pid)
        if not place.get("name"):
            raise HTTPException(status_code=404, detail="플레이스 정보를 찾을 수 없습니다")
        analysis = crawler.analyze_place_seo(place)
        return {"place": place, "analysis": analysis}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("api_place_seo error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


@app.get("/api/place/blog-draft")
def api_place_blog_draft(place_id: str = Query(..., min_length=1, max_length=200)):
    """플레이스 데이터 기반 블로그 초안 생성 — place_id 또는 플레이스 URL 입력 (API 키 불필요)"""
    pid = crawler.parse_place_id(place_id)
    if not pid:
        raise HTTPException(status_code=422, detail="유효한 플레이스 ID가 아닙니다")
    try:
        place = crawler.fetch_place_by_id(pid)
        if not place.get("name"):
            raise HTTPException(status_code=404, detail="플레이스 정보를 찾을 수 없습니다")
        draft = crawler.generate_blog_draft(place)
        return draft
    except HTTPException:
        raise
    except Exception as e:
        logger.error("api_place_blog_draft error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)


_ALLOWED_IMG_SUFFIXES = ("pstatic.net", "naver.net")


def _is_allowed_image_url(raw_url: str) -> bool:
    """URL scheme이 HTTPS이고 hostname이 허용된 네이버 도메인인지 검증 (SSRF 방지)."""
    try:
        if not raw_url.startswith("https://"):
            return False
        hostname = urlparse(raw_url).hostname or ""
        return any(
            hostname == s or hostname.endswith("." + s)
            for s in _ALLOWED_IMG_SUFFIXES
        )
    except Exception:
        return False


@app.get("/api/image-proxy")
def image_proxy(url: str = Query(..., min_length=1)):
    """네이버 이미지 프록시 (Referer 헤더 주입)"""
    if not _is_allowed_image_url(url):
        raise HTTPException(status_code=400, detail="허용되지 않는 이미지 도메인")

    try:
        resp = req.get(
            url,
            headers={
                **crawler.BROWSER_HEADERS,
                "Referer": "https://blog.naver.com",
            },
            timeout=5,
        )
        resp.raise_for_status()
    except req.RequestException as e:
        logger.error("image_proxy request error: %s", e)
        raise HTTPException(status_code=502, detail=_EXT_SVC_ERROR)

    if len(resp.content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기가 너무 큽니다")

    _ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}
    raw_ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    content_type = raw_ct if raw_ct in _ALLOWED_IMAGE_TYPES else "image/jpeg"
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=os.getenv("DEV_RELOAD", "false").lower() == "true")
