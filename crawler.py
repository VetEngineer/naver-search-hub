"""네이버 크롤링 모듈 — Search API + 블로그 본문 스크래핑"""

import json
import logging
import re
import time
import defusedxml.ElementTree as ET

logger = logging.getLogger(__name__)

import requests
from bs4 import BeautifulSoup

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def strip_html(text: str) -> str:
    """HTML 태그 제거"""
    return re.sub(r"<[^>]+>", "", text)


def _naver_headers(client_id: str, client_secret: str) -> dict:
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }


# ──────────────────────────────────────────
# Search API
# ──────────────────────────────────────────

def search_shopping(
    query: str, client_id: str, client_secret: str,
    display: int = 30, start: int = 1, sort: str = "sim",
) -> dict:
    """네이버 쇼핑 검색 API"""
    resp = requests.get(
        "https://openapi.naver.com/v1/search/shop.json",
        params={"query": query, "display": display, "start": start, "sort": sort},
        headers=_naver_headers(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    items = []
    for item in data.get("items", []):
        items.append({
            "title": strip_html(item.get("title", "")),
            "link": item.get("link", ""),
            "image": item.get("image", ""),
            "lprice": int(item.get("lprice", 0) or 0),
            "hprice": int(item.get("hprice", 0) or 0),
            "mallName": item.get("mallName", ""),
            "brand": item.get("brand", ""),
            "maker": item.get("maker", ""),
            "category1": item.get("category1", ""),
            "category2": item.get("category2", ""),
            "category3": item.get("category3", ""),
            "productType": item.get("productType", ""),
        })

    return {
        "total": data.get("total", 0),
        "items": items,
    }


def search_blog(
    query: str, client_id: str, client_secret: str,
    display: int = 20, start: int = 1, sort: str = "sim",
) -> dict:
    """네이버 블로그 검색 API"""
    resp = requests.get(
        "https://openapi.naver.com/v1/search/blog.json",
        params={"query": query, "display": display, "start": start, "sort": sort},
        headers=_naver_headers(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    items = []
    for item in data.get("items", []):
        blog_url = item.get("link", "")
        blog_id, log_no = extract_blog_ids(blog_url)

        items.append({
            "title": strip_html(item.get("title", "")),
            "description": strip_html(item.get("description", "")),
            "link": blog_url,
            "bloggername": item.get("bloggername", ""),
            "postdate": item.get("postdate", ""),
            "blogId": blog_id,
            "logNo": log_no,
        })

    return {
        "total": data.get("total", 0),
        "items": items,
    }


# ──────────────────────────────────────────
# 블로그 본문 크롤링
# ──────────────────────────────────────────

def extract_blog_id_from_url(url: str) -> str:
    """블로그 URL에서 blogId만 추출 (다양한 형태 대응)"""
    url = url.strip().replace("m.blog.naver.com", "blog.naver.com")

    match = re.search(r"blog\.naver\.com/([^/?#]+)", url)
    if match:
        return match.group(1)

    id_match = re.search(r"blogId=([^&]+)", url)
    if id_match:
        return id_match.group(1)

    # URL이 아닌 blogId 자체일 수 있음
    if re.match(r"^[a-zA-Z0-9_]+$", url):
        return url

    return ""


def fetch_blog_post_list(blog_id: str) -> dict:
    """블로그 글 목록 가져오기 (RSS 우선, 실패 시 페이지 크롤링)"""
    if not blog_id:
        return {"blogId": blog_id, "blogName": "", "posts": [], "error": "blogId가 비어있습니다"}

    # RSS 시도
    rss_result = _fetch_blog_rss(blog_id)
    if rss_result["posts"]:
        return rss_result

    # RSS 실패 시 페이지 크롤링 fallback
    return _fetch_blog_page(blog_id)


def _fetch_blog_rss(blog_id: str) -> dict:
    """RSS 피드로 글 목록 가져오기 (경량, 밴 위험 낮음)"""
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except requests.RequestException:
        return {"blogId": blog_id, "blogName": "", "posts": []}

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return {"blogId": blog_id, "blogName": "", "posts": []}

    channel = root.find("channel")
    blog_name = ""
    if channel is not None:
        title_el = channel.find("title")
        blog_name = title_el.text if title_el is not None else ""

    posts = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")
        desc_el = item.find("description")

        link = link_el.text if link_el is not None else ""
        _, log_no = extract_blog_ids(link)

        posts.append({
            "title": strip_html(title_el.text) if title_el is not None and title_el.text else "",
            "link": link,
            "blogId": blog_id,
            "logNo": log_no,
            "pubDate": pub_date_el.text if pub_date_el is not None else "",
            "description": strip_html(desc_el.text)[:200] if desc_el is not None and desc_el.text else "",
        })

    return {"blogId": blog_id, "blogName": blog_name, "posts": posts}


def _fetch_blog_page(blog_id: str) -> dict:
    """PostList 페이지 크롤링 fallback"""
    try:
        resp = requests.get(
            "https://blog.naver.com/PostList.naver",
            params={"blogId": blog_id, "from": "postList", "categoryNo": "0"},
            headers=BROWSER_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except requests.RequestException as e:
        logger.warning("_fetch_blog_page failed blogId=%s: %s", blog_id, e)
        return {"blogId": blog_id, "blogName": "", "posts": [], "error": "블로그 목록 수집 실패"}

    soup = BeautifulSoup(resp.text, "html.parser")

    blog_name = ""
    nick_tag = soup.select_one(".nick") or soup.select_one(".blog_name")
    if nick_tag:
        blog_name = nick_tag.get_text(strip=True)

    posts = []
    for a_tag in soup.select('a[href*="logNo="]'):
        href = a_tag.get("href", "")
        _, log_no = extract_blog_ids(href)
        if not log_no:
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 2:
            continue

        posts.append({
            "title": title,
            "link": f"https://blog.naver.com/{blog_id}/{log_no}",
            "blogId": blog_id,
            "logNo": log_no,
            "pubDate": "",
            "description": "",
        })

    # 중복 제거
    seen = set()
    unique_posts = []
    for p in posts:
        if p["logNo"] not in seen:
            seen.add(p["logNo"])
            unique_posts.append(p)

    return {"blogId": blog_id, "blogName": blog_name, "posts": unique_posts}


def crawl_multiple_blog_lists(blog_ids: list[str], delay: float = 1.5) -> list[dict]:
    """다수 블로그의 글 목록을 순차적으로 수집 (밴 방지 딜레이 적용)"""
    results = []
    for i, blog_id in enumerate(blog_ids):
        result = fetch_blog_post_list(blog_id)
        results.append(result)
        if i < len(blog_ids) - 1:
            time.sleep(delay)
    return results


def crawl_posts_content(
    posts: list[dict], delay: float = 2.0,
) -> list[dict]:
    """선택된 글들의 본문을 순차적으로 크롤링 (밴 방지 딜레이 적용)"""
    results = []
    for i, post in enumerate(posts):
        blog_id = post.get("blogId", "")
        log_no = post.get("logNo", "")
        try:
            content = fetch_blog_content(blog_id, log_no)
            results.append(content)
        except Exception as e:
            logger.warning("crawl_posts_content failed blogId=%s logNo=%s: %s", blog_id, log_no, e)
            results.append({
                "blogId": blog_id,
                "logNo": log_no,
                "error": "본문 수집 실패",
                "url": f"https://blog.naver.com/{blog_id}/{log_no}",
            })
        if i < len(posts) - 1:
            time.sleep(delay)
    return results


def extract_blog_ids(url: str) -> tuple[str, str]:
    """블로그 URL에서 blogId, logNo 추출"""
    match = re.search(r"blog\.naver\.com/([^/?]+)/(\d+)", url)
    if match:
        return match.group(1), match.group(2)

    id_match = re.search(r"blogId=([^&]+)", url)
    no_match = re.search(r"logNo=(\d+)", url)
    if id_match and no_match:
        return id_match.group(1), no_match.group(1)

    return "", ""


def fetch_blog_content(blog_id: str, log_no: str) -> dict:
    """블로그 본문 추출 (PostView 직접 호출)"""
    if not blog_id or not log_no:
        return {"error": "blogId 또는 logNo가 없습니다"}

    try:
        resp = requests.get(
            "https://blog.naver.com/PostView.naver",
            params={"blogId": blog_id, "logNo": log_no},
            headers=BROWSER_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch_blog_content failed blogId=%s logNo=%s: %s", blog_id, log_no, e)
        return {"error": "본문 수집 실패", "blogId": blog_id, "logNo": log_no, "title": "", "text": "", "images": [], "url": ""}
    resp.encoding = "utf-8"
    url = resp.url
    soup = BeautifulSoup(resp.text, "html.parser")

    # 제목 (에디터 버전 분기)
    title_tag = (
        soup.select_one(".se-title-text")
        or soup.select_one(".pcol1 .itemSubjectBoldfont")
    )
    title = title_tag.get_text(strip=True) if title_tag else ""

    # 본문 (에디터 버전 분기)
    content_tag = (
        soup.select_one(".se-main-container")
        or soup.select_one("#postViewArea")
    )
    text = content_tag.get_text(separator="\n", strip=True) if content_tag else ""

    # 이미지 URL 추출 — 3가지 소스를 모두 탐색
    images = _extract_images(content_tag) if content_tag else []

    return {
        "blogId": blog_id,
        "logNo": log_no,
        "title": title,
        "text": text,
        "images": images,
        "url": url,
    }


# ──────────────────────────────────────────
# 플레이스 (Local Search API + 모바일 웹 스크래핑)
# ──────────────────────────────────────────

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://m.place.naver.com/",
}


def search_place(query: str, display: int = 5) -> dict:
    """네이버 플레이스 검색 — 통합검색 결과 파싱 (API 키 불필요)

    네이버 통합검색의 .place-app-root 영역에서
    업체명, 전화, 주소, 방문자 리뷰 수, 블로그 리뷰 수를 추출한다.
    """
    resp = requests.get(
        "https://search.naver.com/search.naver",
        params={"query": query, "where": "nexearch"},
        headers=BROWSER_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    root = soup.select_one(".place-app-root")
    if not root:
        return {"total": 0, "items": []}

    text = root.get_text("|", strip=True)

    # placeId 추출 (링크에서)
    place_ids = []
    for a_tag in root.select("a[href]"):
        href = a_tag.get("href", "")
        m = re.search(r"place/(\d+)", href)
        if m and m.group(1) not in place_ids:
            place_ids.append(m.group(1))

    items = _parse_place_cards(text, place_ids, display)
    # total은 파싱된 건수 (네이버 통합검색 전체 건수 아님)
    return {"total": len(items), "parsed": True, "items": items}


_PLACE_SKIP = frozenset({
    "플레이스", "플레이스 플러스", "플레이스 검색결과 안내",
    "내 업체 등록", "신규장소 등록", "로딩중", "더보기",
    "네이버페이", "톡톡", "쿠폰", "광고", "안내",
    "상세주소", "열기", "길찾기", "거리뷰", "공유", "예약", "주문", "저장",
    "휠체어 출입 가능", "전화번호 보기", "현재 위치에서",
    "전체필터", "영업중", "포장주문", "실시간예약", "업체명 검색하기",
    "마케팅", "우리동네", "새로오픈",
    # 추가: 평점/리뷰 UI 텍스트
    "별점", "리뷰", "포토 리뷰", "방문자 리뷰", "블로그 리뷰",
    "알림받기", "알림", "이벤트", "할인", "할인 쿠폰",
    "포토 리뷰 이벤트 쿠폰", "스마트 주문", "네이버 예약",
    "테이블링", "캐치테이블", "원테이블", "웨이팅",
    "영수증 리뷰", "방문", "찜", "메뉴 보기", "전화",
})

_ADDR_PREFIX = re.compile(
    r'^(?:서울|경기|부산|인천|대구|대전|광주|울산|세종|강원'
    r'|충[북남]|전[북남]|경[북남]|제주'
    r'|평택|남양주|제천|창녕|포항|수원|성남|고양|용인|안산|안양'
    r'|의정부|김포|파주|화성|양주|구리|하남|광명|시흥|군포|오산|이천|양평'
    r'|춘천|원주|청주|천안|아산|전주|목포|여수|순천|경주|구미|거제|통영'
    r'|양산|진주|김해|창원|마산|진해'
    r')\s'
)

_NAME_DENY = re.compile(
    r'(?:별점|리뷰|쿠폰|이벤트|할인|알림|포토|영수증|스마트|예약|찜|웨이팅'
    r'|테이블링|캐치|원테이블|카카오|네이버|주문|결제|혜택)'
)


def _parse_place_cards(text: str, place_ids: list[str], display: int) -> list[dict]:
    """통합검색 플레이스 텍스트에서 장소 카드를 추출 (3가지 패턴 통합)"""
    items = []

    # 패턴 A: "업체명|네이버페이|전화|...|방문자 리뷰|N|블로그 리뷰|N"
    pat_a = (
        r'([^|]+)\|네이버페이\|(\d[\d-]+)\|'
        r'[^|]*\|[^|]*\|'
        r'([^|]+)\|[^|]*\|[^|]*\|(?:영업[^|]*)\|'
        r'방문자 리뷰\|([\d,]+)\|블로그 리뷰\|([\d,]+)'
    )
    matches_a = re.findall(pat_a, text)
    if matches_a:
        for i, m in enumerate(matches_a[:display]):
            pid = place_ids[i] if i < len(place_ids) else ""
            items.append(_mk(
                name=m[0].strip(), phone=m[1],
                addr=m[2].split("|")[0].strip(),
                visitor=int(m[3].replace(",", "")),
                blog=int(m[4].replace(",", "")),
                pid=pid,
            ))
        return items

    # 패턴 B: "이미지수|N|업체명|..." 로 카드 분리
    if "이미지수|" in text:
        cards = re.split(r'(?:이미지수\|\d+\||우리동네\|)', text)
        pid_idx = 0
        for card in cards:
            card = card.strip("|").strip()
            if len(card) < 10:
                continue
            parsed = _parse_one_card(card)
            pid = place_ids[pid_idx] if pid_idx < len(place_ids) else ""
            pid_idx += 1
            if parsed["name"]:
                items.append(_mk(**parsed, pid=pid))
            if len(items) >= display:
                break
        return items

    # 패턴 C: 리뷰|N 앵커 기반 (홍대 카페 등)
    for i, rm in enumerate(re.finditer(r'리뷰\|([\d,.만]+)', text)):
        if len(items) >= display:
            break
        before = text[max(0, rm.start() - 300):rm.start()]
        after = text[rm.start():rm.start() + 200]
        name = _find_name_reverse(before)
        rv = _parse_review_count(rm.group(1))
        addr = _find_addr(before + after)
        pid = place_ids[i] if i < len(place_ids) else ""
        if name:
            items.append(_mk(name=name, addr=addr, visitor=rv, pid=pid))

    return items


def _parse_one_card(card: str) -> dict:
    """개별 카드 텍스트 → {name, category, phone, addr}"""
    parts = card.split("|")
    name = category = phone = addr = ""
    for p in parts:
        p = p.strip()
        if not p or p in _PLACE_SKIP:
            continue
        if re.match(r'^0\d{2,3}-\d{3,4}-\d{4}$', p):
            phone = p; continue
        if p.startswith("영업") or p.startswith("곧 영업"):
            continue
        if re.match(r'^\d{1,2}:\d{2}', p):
            continue
        if re.match(r'^\d+km$', p):
            continue
        if "쿠폰" in p and len(p) > 5:
            continue
        if _ADDR_PREFIX.match(p):
            addr = p; continue
        if not name and 2 <= len(p) <= 30 and not _NAME_DENY.search(p):
            name = p; continue
        if name and not category and 2 <= len(p) <= 20 and not _NAME_DENY.search(p):
            category = p; continue
    return {"name": name, "category": category, "phone": phone, "addr": addr}


def _find_name_reverse(text: str) -> str:
    """텍스트 끝에서부터 의미있는 업체명 탐색"""
    for p in reversed(text.split("|")):
        p = p.strip()
        if (2 <= len(p) <= 30
            and p not in _PLACE_SKIP
            and not re.match(r'^[\d,.]+$', p)
            and not re.match(r'^\d{2,4}-', p)
            and not p.startswith("영업")
            and not p.startswith("곧 영업")
            and not re.match(r'^\d{1,2}:\d{2}', p)
            and not _ADDR_PREFIX.match(p)
            and "필터" not in p
            and "검색하기" not in p
            and not _NAME_DENY.search(p)
            and not re.match(r'^(?:서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|경기도|강원)', p)):
            return p
    return ""


def _find_addr(text: str) -> str:
    """텍스트에서 주소 추출"""
    m = re.search(
        r'((?:서울|경기|부산|인천|대구|대전|광주|울산|세종|강원'
        r'|충[북남]|전[북남]|경[북남]|제주)\s+\S+\s+\S+)',
        text,
    )
    return m.group(1).split("|")[0].strip() if m else ""


def _parse_review_count(s: str) -> int:
    """'1,234' 또는 '1.2만' → int"""
    s = s.replace(",", "")
    if "만" in s:
        num = s.replace("만", "").strip()
        if not num:
            return 10000
        try:
            return int(float(num) * 10000)
        except ValueError:
            return 10000
    return int(s) if s.isdigit() else 0


def _mk(name="", category="", phone="", addr="", visitor=0, blog=0, pid="") -> dict:
    return {
        "title": name, "telephone": phone,
        "address": addr, "roadAddress": addr,
        "visitorReviewCount": visitor, "blogReviewCount": blog,
        "placeId": pid,
        "link": f"https://m.place.naver.com/place/{pid}/home" if pid else "",
        "category": category, "description": "",
    }


def _search_blog_web(query: str, display: int = 10) -> dict:
    """네이버 블로그 검색 — 웹 스크래핑 (API 키 불필요)"""
    try:
        resp = requests.get(
            "https://search.naver.com/search.naver",
            params={"query": query, "where": "blog"},
            headers=BROWSER_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("_search_blog_web failed query=%r: %s", query, e)
        return {"total": 0, "items": []}
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    seen_links = set()
    for a_tag in soup.select('a[href*="blog.naver.com"]'):
        link = a_tag.get("href", "")
        title = a_tag.get_text(strip=True)

        if not link or not title or len(title) < 5 or link in seen_links:
            continue
        # logNo가 포함된 실제 포스트 링크만
        blog_id, log_no = extract_blog_ids(link)
        if not log_no:
            continue

        seen_links.add(link)
        items.append({
            "title": strip_html(title),
            "description": "",
            "link": link,
            "bloggername": "",
            "postdate": "",
            "blogId": blog_id,
            "logNo": log_no,
        })
        if len(items) >= display:
            break

    # 총 건수 추정
    total_el = soup.select_one(".title_num, .result_num, .sub_text")
    total = len(items)
    if total_el:
        num_match = re.search(r"[\d,]+", total_el.get_text())
        if num_match:
            try:
                total = int(num_match.group().replace(",", ""))
            except ValueError:
                pass

    return {"total": total, "items": items}


def parse_place_id(id_or_url: str) -> str:
    """다양한 형식에서 네이버 플레이스 ID(숫자 문자열)를 추출한다.

    지원 형식:
    - 숫자 문자열: "31863524"
    - map.naver.com: "https://map.naver.com/p/entry/place/31863524?..."
    - m.place.naver.com: "https://m.place.naver.com/place/31863524/home"
    - pcmap.place.naver.com: "https://pcmap.place.naver.com/place/31863524/home"
    """
    s = (id_or_url or "").strip()
    if re.match(r"^\d+$", s):
        return s

    m = re.search(r"/place/(\d+)", s)
    if m:
        return m.group(1)

    return ""


def _extract_place_script(text: str) -> str:
    """HTML 응답에서 플레이스 데이터가 담긴 스크립트 블록을 반환한다.

    BeautifulSoup을 사용해 파싱 정확도를 높이고 대형 HTML에서의
    regex backtracking 위험을 방지한다.
    """
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all("script"):
        content = tag.get_text() or ""
        if "visitorReviewsTotal" in content or "PlaceDetailBase" in content:
            return content.replace("\\\\u002F", "/").replace("\\u002F", "/")
    return ""


def _decode_unicode_escapes(s: str) -> str:
    """JSON 유니코드 이스케이프(\\uXXXX)를 실제 문자로 변환한다."""
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)


def _fetch_place_introduction(place_id: str) -> str:
    """네이버 플레이스 정보 탭에서 업체 소개(introduction) 텍스트를 추출한다.

    정보 탭 HTML에 서버사이드 렌더링된 업체 소개가 포함되어 있다.
    - 1순위: svg.JcVkK 다음 형제 div (업체 소개 컨테이너)
    - 2순위: 페이지 내 가장 긴 잎(leaf) 텍스트 블록 (200자 이상)
    """
    try:
        resp = requests.get(
            f"https://m.place.naver.com/place/{place_id}/information",
            headers=MOBILE_HEADERS, timeout=10,
        )
        if resp.status_code != 200:
            return ""
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1순위: svg.JcVkK 기준 — 업체 소개 섹션의 expand 아이콘 바로 다음 div
        svg = soup.find("svg", class_="JcVkK")
        if svg:
            next_div = svg.find_next_sibling("div")
            if next_div:
                text = next_div.get_text(separator="\n", strip=True)
                if len(text) > 20:
                    return text

        # 2순위: 자식 태그가 없는 가장 긴 단일 텍스트 블록
        best = ""
        for tag in soup.find_all(["div", "p"]):
            child_tags = [c for c in tag.children if hasattr(c, "name") and c.name]
            if child_tags:
                continue
            t = tag.get_text(strip=True)
            if len(t) > len(best) and len(t) > 200:
                best = t
        return best
    except Exception:
        return ""


def _parse_place_json(script: str, place_id: str) -> dict:
    """스크립트 블록에서 플레이스 기본 정보를 추출한다."""
    def _first(pattern: str, text: str = "") -> str:
        m = re.search(pattern, text or script)
        return m.group(1) if m else ""

    def _int_in(pattern: str, text: str = "", flags: int = 0) -> int:
        m = re.search(pattern, text or script, flags)
        return int(m.group(1)) if m else 0

    def _float_in(pattern: str, text: str = "") -> float:
        m = re.search(pattern, text or script)
        return float(m.group(1)) if m else 0.0

    pdb_start = script.find(f"PlaceDetailBase:{place_id}")
    # 10000자로 확장 — 메뉴/이미지 많은 업체에서 category 누락 방지
    pdb = script[pdb_start:pdb_start + 10000] if pdb_start >= 0 else ""

    # name은 PlaceDetailBase 섹션 우선, 없으면 전체 스크립트 fallback
    name = (
        (_first(r'"name":"([^"]+)"', pdb) if pdb else "")
        or _first(r'"name":"([^"]+)"')
    )
    # category도 pdb 우선, 전체 fallback
    category = (
        re.search(r'"category":"([^"]+)"', pdb) if pdb
        else None
    ) or re.search(r'"category":"([^"]+)"', script)
    road_address = _first(r'"roadAddress":"([^"]+)"')
    address = _first(r'"address":"([^"]+)"')
    phone = re.search(r'"virtualPhone":"([^"]+)"', script) or re.search(r'"phone":"([^"]+)"', script)
    # visitorReviewsTextReviewTotal: 네이버 UI 표시 기준 (텍스트 리뷰만)
    # visitorReviewsTotal: 텍스트+사진 전체 (항상 >= TextReviewTotal)
    visitor = (
        _int_in(r'"visitorReviewsTextReviewTotal"\s*:\s*(\d+)')
        or _int_in(r'"visitorReviewsTotal"\s*:\s*(\d+)')
    )
    # 방문자 리뷰 평점 (네이버 UI 표시값)
    score = _float_in(r'"visitorReviewsScore"\s*:\s*([0-9.]+)')

    # blog_total: FsasReviewsResult.total 우선 (파라미터화된 키 대응), blogCafeReviewCount fallback
    blog_total = (
        _int_in(r'FsasReviewsResult","total"\s*:\s*(\d+)')
        or _int_in(r'"blogCafeReviewCount"\s*:\s*(\d+)')
    )

    # description: introduction 필드 우선, 없으면 빈 문자열
    # 실제 업체 소개는 information 탭 HTML에서 별도 추출 (fetch_place_by_id 참조)
    intro_m = re.search(r'"introduction":"([^"]*)"', script)
    description = intro_m.group(1) if (intro_m and len(intro_m.group(1)) > 5) else ""

    # 예약 연동: InformationFacilities:1 (예약) 또는 bookingUrl 존재 여부
    has_booking = bool(
        re.search(r'"InformationFacilities:1"', script) or
        re.search(r'"bookingUrl"\s*:\s*"https://booking\.naver', script)
    )
    # 쿠폰 등록: couponYn:Y, hasCoupon:true, 또는 coupon 비빈 문자열
    has_coupon = bool(
        re.search(r'"couponYn"\s*:\s*"Y"', script) or
        re.search(r'"hasCoupon"\s*:\s*true', script) or
        re.search(r'"coupon"\s*:\s*"[가-힣A-Za-z]{2,}"', script)
    )

    # 이미지: \\uXXXX 유니코드 이스케이프 디코딩 후 ldb-phinf URL 추출
    # (스크립트 내 URL이 JSON 이스케이프 형태로 저장됨)
    decoded_script = _decode_unicode_escapes(script)
    images = list(dict.fromkeys(
        re.findall(r"https://ldb-phinf\.pstatic\.net/[^\"\\\s<>]+", decoded_script)
    ))

    menu_raw = re.findall(
        r'"Menu:\d+_\d+"[^{]*\{[^}]*"name":"([^"]+)"[^}]*"price":"([^"]*)"',
        script,
    )
    menus = [{"name": n, "price": p} for n, p in menu_raw]

    return {
        "name": name,
        "category": category.group(1) if category else "",
        "roadAddress": road_address,
        "address": address,
        "phone": phone.group(1) if phone else "",
        "description": description,
        "visitorReviewCount": visitor,
        "visitorReviewScore": round(score, 2) if score else 0.0,
        "blogReviewCount": blog_total,
        "hasBooking": has_booking,
        "hasCoupon": has_coupon,
        "images": images,
        "imageCount": len(images),
        "menuInfo": menus,
    }


def fetch_place_by_id(place_id: str) -> dict:
    """place_id(숫자 문자열)로 네이버 플레이스 상세 정보를 수집한다.

    반환 dict 구조:
        name, category, roadAddress, address, phone, description,
        link, placeUrl, placeId, visitorReviewCount, blogReviewCount,
        saveCount, blogReviews, images, menuInfo, keywords
    """
    base: dict = {
        "name": "", "category": "", "roadAddress": "", "address": "",
        "phone": "", "description": "", "link": "", "placeUrl": "",
        "placeId": place_id, "visitorReviewCount": 0, "visitorReviewScore": 0.0,
        "blogReviewCount": 0, "saveCount": 0, "hasBooking": False, "hasCoupon": False,
        "blogReviews": [], "images": [], "imageCount": 0, "menuInfo": [], "keywords": [],
    }

    if not place_id:
        return base

    candidates = [
        f"https://m.place.naver.com/place/{place_id}/home",
        f"https://m.place.naver.com/restaurant/{place_id}/home",
        f"https://m.place.naver.com/cafe/{place_id}/home",
        f"https://m.place.naver.com/hospital/{place_id}/home",
        f"https://m.place.naver.com/hairshop/{place_id}/home",
    ]

    script = ""
    used_url = ""
    for url in candidates:
        try:
            resp = requests.get(url, headers=MOBILE_HEADERS, timeout=3)
            if resp.status_code == 200 and len(resp.text) >= 5000:
                resp.encoding = "utf-8"
                script = _extract_place_script(resp.text)
                if script:
                    used_url = url
                    break
        except requests.RequestException:
            continue

    if not script:
        return base

    parsed = _parse_place_json(script, place_id)
    base = {**base, **parsed}

    place_url = used_url
    base["link"] = place_url
    base["placeUrl"] = place_url

    # keywords — 이미 가져온 script에서 추출 (중복 HTTP 요청 방지)
    base["keywords"] = _extract_keywords_from_script(script)

    # 업체 소개: introduction 필드가 없으면 정보 탭 HTML에서 추출
    if not base.get("description"):
        base["description"] = _fetch_place_introduction(place_id)

    # 블로그 리뷰
    name = base.get("name", "")
    addr_short = ""
    for addr_field in ("roadAddress", "address"):
        if base.get(addr_field):
            parts = base[addr_field].split()
            addr_short = parts[0] if parts else ""
            break
    blog_query = f"{addr_short} {name}".strip() if addr_short else name
    try:
        blog_data = _search_blog_web(blog_query, display=10)
        base["blogReviews"] = blog_data.get("items", [])
    except Exception as e:
        logger.warning("blog_review fetch failed for place %s: %s", place_id, e)

    return base



def _extract_keywords_from_script(text: str) -> list[dict]:
    """이미 가져온 스크립트/HTML 텍스트에서 키워드를 추출한다 (HTTP 요청 없음)."""
    keywords = []
    seen: set[str] = set()

    # 1) keywordList (업체 설정 대표 키워드)
    kl_match = re.search(r'"keywordList":\s*\[([^\]]+)\]', text)
    if kl_match:
        for kw in re.findall(r'"([^"]+)"', kl_match.group(1)):
            if kw not in seen and len(kw) > 1:
                seen.add(kw)
                keywords.append({"keyword": kw, "count": 0, "source": "설정"})

    # 2) votedKeyword (방문자 투표 키워드)
    codes = re.findall(r'"code":"([^"]+)"[^}]*?"count":(\d+)', text)
    codes = [(c, n) for c, n in codes
             if c not in ("total", "taste", "service", "atmosphere", "facility")]
    if codes:
        for code, count in sorted(codes, key=lambda x: int(x[1]), reverse=True)[:10]:
            label = _keyword_code_to_label(code)
            if label not in seen:
                seen.add(label)
                keywords.append({"keyword": label, "count": int(count), "source": "투표"})

    return keywords



def _keyword_code_to_label(code: str) -> str:
    """방문자 키워드 code를 한글 라벨로 변환"""
    mapping = {
        # 카페/음식점
        "coffee_good": "커피맛집", "drink_good": "음료맛집", "kind": "친절해요",
        "dessert_good": "디저트맛집", "store_clean": "매장깨끗", "talk_good": "대화하기좋은",
        "comfy": "편안한", "special_menu": "특별한메뉴", "study_good": "공부하기좋은",
        "interior_cool": "인테리어좋은", "toilet_clean": "화장실깨끗", "view_good": "뷰좋은",
        "price_cheap": "가성비좋은", "photo_good": "사진찍기좋은", "spacious": "넓은",
        "parking_easy": "주차편리", "atmosphere_calm": "분위기좋은", "cozy": "아늑한",
        "food_good": "음식맛있는", "taste_healthy": "건강한맛", "eat_alone": "혼밥",
        "stay_long": "오래있기좋은", "types_various": "메뉴다양", "food_fast": "빠른",
        "menu_good": "메뉴구성좋은", "music_good": "음악좋은", "price_worthy": "가격합리적",
        "bread_good": "빵맛집", "custom_good": "커스텀좋은", "large": "양많은",
        "together": "함께하기좋은",
        # 자동차/서비스
        "work_fast": "작업빠른", "check_thorough": "꼼꼼한작업", "explanation_detail": "설명친절",
        "price_reasonable": "가격합리적", "facility_good": "시설좋은",
        "equipment_latest_new": "최신장비", "vehicle_supplies": "차량용품",
        "mood_comfy": "편안한분위기", "wait_short": "대기짧은",
        # 병원/헤어
        "skill_good": "실력좋은", "hygiene_good": "위생좋은", "consultation_kind": "상담친절",
        "result_good": "결과만족", "reservation_easy": "예약편리",
        "treatment_gentle": "시술부드러운", "parking_convenient": "주차편리",
        "revisit_want": "재방문의사",
    }
    return mapping.get(code, code)


def analyze_place_seo(place: dict) -> dict:
    """플레이스 SEO/AEO/GEO 분석 및 최적화 제안

    premium=True 항목은 단순 존재 확인이 아닌 품질/연동 분석으로,
    작성/등록만으로는 통과되지 않는 심층 지표입니다.
    """
    checks = []
    score = 0
    max_score = 0

    def check(name: str, passed: bool, weight: int, tip: str, category: str, premium: bool = False):
        nonlocal score, max_score
        max_score += weight
        if passed:
            score += weight
        checks.append({
            "name": name,
            "passed": passed,
            "weight": weight,
            "tip": tip,
            "category": category,
            "premium": premium,
        })

    name = place.get("name", "")
    desc = place.get("description", "")
    category = place.get("category", "")
    reviews = place.get("blogReviews", [])
    keywords = place.get("keywords", [])

    # ── SEO (네이버 플레이스 내부 검색) ──
    check("업체명 등록", bool(name), 10, "업체명이 비어있습니다.", "SEO")
    check("카테고리 설정", bool(category), 8, "카테고리가 정확해야 관련 검색에 노출됩니다.", "SEO")
    check("도로명 주소", bool(place.get("roadAddress")), 7, "도로명 주소가 있어야 지역 검색에 유리합니다.", "SEO")
    check("전화번호", bool(place.get("phone")), 5, "전화번호가 있으면 신뢰도가 올라갑니다.", "SEO")
    check("업체 소개 작성", bool(desc), 4, "업체 소개를 작성하세요 (지역+업종+특징 포함 권장).", "SEO")
    check("플레이스 링크 존재", bool(place.get("link")), 5, "네이버 플레이스에 등록되어 있어야 지도 검색에 노출됩니다.", "SEO")

    visitor_count = place.get("visitorReviewCount", 0)
    check("방문자 리뷰 존재", visitor_count > 0, 8, "방문자 리뷰가 많을수록 플레이스 순위에 유리합니다.", "SEO")
    check("방문자 리뷰 100개 이상", visitor_count >= 100, 5, f"현재 {visitor_count:,}건. 100개 이상이면 신뢰도가 높아집니다.", "SEO")
    check("방문자 리뷰 500개 이상", visitor_count >= 500, 3, f"현재 {visitor_count:,}건. 500개 이상이면 경쟁 키워드에서도 강합니다.", "SEO")

    blog_count = place.get("blogReviewCount", 0)
    check("블로그 리뷰 존재", blog_count > 0, 10, "블로그 리뷰는 플레이스 SEO에 가장 큰 영향을 줍니다.", "SEO")
    check("블로그 리뷰 10개 이상", blog_count >= 10, 8, f"현재 {blog_count}건. 블로그 리뷰가 많을수록 상위 노출됩니다.", "SEO")
    check("블로그 리뷰 50개 이상", blog_count >= 50, 5, f"현재 {blog_count}건. 50개 이상이면 경쟁 키워드에서도 강합니다.", "SEO")

    # ── SEO Premium ──
    # 업체명 최적화: 업종/서비스 키워드가 업체명에 녹아있는지 분석
    # (단순 브랜드명보다 키워드 포함 시 검색 노출에 유리)
    _seo_kws = ["전문", "공방", "카페", "식당", "병원", "클리닉", "헤어", "뷰티",
                "마트", "약국", "치과", "한의원", "학원", "PC방", "노래방",
                "세탁", "수리", "정비", "코칭", "컨설팅", "스튜디오", "센터"]
    _cat_words = [w for w in category.replace(",", " ").split() if len(w) > 1]
    name_has_kw = any(kw in name for kw in _seo_kws + _cat_words)
    _name_len_ok = 2 <= len(name) <= 20
    check(
        "업체명 최적화",
        name_has_kw and _name_len_ok,
        6,
        "업체명에 업종·서비스 키워드를 포함하면 연관 검색에 더 자주 노출됩니다. "
        "예: '○○자동차정비' vs '○○'",
        "SEO", premium=True,
    )
    # 네이버 예약 연동
    check(
        "네이버 예약 연동",
        bool(place.get("hasBooking")),
        8,
        "네이버 예약을 연동하면 플레이스 노출 순위 가점 및 전환율이 높아집니다.",
        "SEO", premium=True,
    )
    # 쿠폰/혜택 등록
    check(
        "쿠폰·혜택 등록",
        bool(place.get("hasCoupon")),
        6,
        "쿠폰을 등록하면 플레이스 카드에 '쿠폰' 뱃지가 표시되어 클릭률이 높아집니다.",
        "SEO", premium=True,
    )

    # ── AEO (Answer Engine Optimization) ──
    check(
        "구조화된 기본 정보 완성",
        all([name, category, place.get("roadAddress") or place.get("address"), place.get("phone")]),
        12, "이름/카테고리/주소/전화 4가지가 모두 있어야 AI 답변에 인용됩니다.", "AEO",
    )
    check(
        "카테고리에 업종 키워드 포함",
        bool(category) and len(category) > 2, 5,
        "구체적인 카테고리 (예: '이탈리안레스토랑')가 '음식점'보다 AEO에 유리합니다.", "AEO",
    )

    # AEO Premium: 설명 품질 분석
    # 단순 작성 여부가 아닌 길이·지역명·업종 키워드 포함 여부를 종합 평가
    _addr = place.get("roadAddress") or place.get("address") or ""
    # 주소 앞 3단어에서 행정구역 접미사(시/구/동/읍/면/로/길) 제거해 핵심 지역명 추출
    # 예: "평택시" → "평택", "서정동" → "서정"
    _raw_region = [w for w in _addr.split()[:3] if len(w) > 1]
    _region_words = []
    for w in _raw_region:
        _region_words.append(w)
        # 접미사 제거 버전도 추가 (평택시→평택, 서정동→서정 등)
        stripped = re.sub(r'(시|구|군|동|읍|면|로|길|대로)$', '', w)
        if stripped and stripped != w and len(stripped) > 1:
            _region_words.append(stripped)
    _desc_has_region = any(w in desc for w in _region_words) if _region_words else False
    _desc_has_cat = any(w in desc for w in _cat_words) if _cat_words else False
    _desc_long = len(desc) >= 50
    check(
        "설명 품질: 50자 이상",
        _desc_long, 6,
        f"현재 {len(desc)}자. 50자 이상의 구체적인 소개가 AI 이해도를 높입니다.", "AEO", premium=True,
    )
    check(
        "설명에 지역명·업종 키워드 포함",
        _desc_has_region or _desc_has_cat,
        8,
        "설명에 지역명(예: '평택', '서정동')과 업종 키워드를 자연스럽게 포함하세요.",
        "AEO", premium=True,
    )

    # ── GEO (Generative Engine Optimization) ──
    check(
        "블로그 리뷰 20개 이상 (GEO)",
        blog_count >= 20, 10,
        f"현재 {blog_count}건. 생성형 AI는 다양한 블로그 리뷰를 주요 소스로 사용합니다.", "GEO",
    )
    check(
        "블로그 리뷰 100개 이상 (GEO)",
        blog_count >= 100, 7,
        f"현재 {blog_count}건. 블로그 리뷰 100개 이상이면 생성형 AI 응답에 인용될 확률이 크게 높아집니다.", "GEO",
    )

    # GEO Premium: 리뷰 텍스트 분석
    # 방문자 키워드 다양성 — 단순 건수가 아닌 키워드 질로 평가
    _kw_count = len(keywords)
    check(
        "방문자 키워드 5종 이상",
        _kw_count >= 5,
        8,
        f"현재 {_kw_count}종. 방문자 리뷰 키워드가 다양할수록 AI가 업체 특징을 다각도로 파악합니다.",
        "GEO", premium=True,
    )
    # 블로그 리뷰 제목·본문에 업체명 언급 여부
    name_in_reviews = any(
        name in (r.get("title", "") + r.get("description", "")) for r in reviews
    ) if name and reviews else False
    check(
        "블로그 리뷰에 업체명 언급",
        name_in_reviews, 5,
        "블로그 리뷰 제목/본문에 업체명이 있으면 AI가 업체-리뷰를 정확히 연결합니다.",
        "GEO", premium=True,
    )
    # 설명의 GEO 키워드 (추천/전문/대표 등)
    has_geo_kw = any(kw in desc for kw in ["전문", "특징", "추천", "인기", "대표"]) if desc else False
    check(
        "설명에 추천·특징 키워드",
        has_geo_kw, 5,
        "업체 설명에 '전문', '대표', '추천' 등이 있으면 AI 인용 확률이 올라갑니다.",
        "GEO", premium=True,
    )

    total_pct = round((score / max_score) * 100) if max_score > 0 else 0
    grade = "A" if total_pct >= 80 else "B" if total_pct >= 60 else "C" if total_pct >= 40 else "D"

    # 카테고리별 점수
    categories = {}
    for c in checks:
        cat = c["category"]
        if cat not in categories:
            categories[cat] = {"score": 0, "max": 0, "checks": []}
        categories[cat]["max"] += c["weight"]
        if c["passed"]:
            categories[cat]["score"] += c["weight"]
        categories[cat]["checks"].append(c)

    cat_scores = {}
    for cat, data in categories.items():
        cat_scores[cat] = {
            "score": data["score"],
            "max": data["max"],
            "pct": round((data["score"] / data["max"]) * 100) if data["max"] > 0 else 0,
        }

    return {
        "totalScore": score,
        "maxScore": max_score,
        "pct": total_pct,
        "grade": grade,
        "categoryScores": cat_scores,
        "checks": checks,
        "topImprovements": [c for c in checks if not c["passed"]][:5],
    }


def generate_blog_draft(place: dict) -> dict:
    """플레이스 데이터를 기반으로 블로그 초안 생성 (AI 없이 템플릿 기반)"""
    name = (place.get("name") or "")[:50]
    category = (place.get("category") or "")[:50]
    address = ((place.get("roadAddress") or place.get("address")) or "")[:100]
    phone = (place.get("phone") or "")[:20]
    description = (place.get("description") or "")[:500]
    hours = place.get("businessHours", [])
    menus = place.get("menuInfo", [])
    keywords = place.get("keywords", [])
    images = place.get("images", [])
    blog_reviews = place.get("blogReviews", [])
    review_count = place.get("visitorReviewCount", 0)
    blog_review_count = place.get("blogReviewCount", 0)

    # 키워드 추출
    top_keywords = sorted(keywords, key=lambda k: k.get("count", 0), reverse=True)[:5]
    kw_str = ", ".join(k["keyword"] for k in top_keywords) if top_keywords else ""

    # 메뉴 텍스트
    menu_lines = []
    for m in menus[:10]:
        price = m.get("price", "")
        line = f"- {m.get('name', '')}" + (f" ({price})" if price else "")
        menu_lines.append(line)
    menu_text = ("\n".join(menu_lines) if menu_lines else "(메뉴 정보 없음)")[:300]

    # 영업시간 텍스트
    hours_text = ""
    if isinstance(hours, list) and hours:
        hours_text = " / ".join(str(h) for h in hours[:7])
    elif isinstance(hours, str):
        hours_text = hours

    # 블로그 초안 생성
    title = f"{name} 방문 후기 | {category} 추천"
    if kw_str:
        title += f" ({kw_str.split(',')[0].strip()})"

    sections = [
        f"# {name} 솔직 방문 후기\n",
        f"**{category}** | {address}\n",
    ]

    if description:
        sections.append(f"## 한줄 소개\n{description}\n")

    if kw_str:
        sections.append(f"## 방문자들이 뽑은 키워드\n{kw_str}\n")

    sections.append(f"## 메뉴\n{menu_text}\n")

    if hours_text:
        sections.append(f"## 영업시간\n{hours_text}\n")

    sections.append(f"## 기본 정보\n- 주소: {address}\n- 전화: {phone}\n- 방문자 리뷰: {review_count}개\n- 블로그 리뷰: {blog_review_count}개\n")

    sections.append("## 방문 후기\n(여기에 직접 작성한 후기를 넣으세요)\n")

    # 블로그 리뷰 요약
    blog_snippets = ""
    for br in blog_reviews[:5]:
        blog_snippets += f"- [{br.get('bloggername','')[:30]}] {br.get('title','')[:60]}: {br.get('description','')[:80]}\n"
    blog_snippets = blog_snippets[:300]

    # AI 프롬프트 제안
    ai_prompt = f"""다음 정보를 바탕으로 네이버 블로그에 올릴 {name} 방문 후기를 작성해주세요.

업체명: {name}
카테고리: {category}
주소: {address}
전화: {phone}
메뉴: {menu_text}
업체 소개: {description}

기존 블로그 리뷰 참고:
{blog_snippets if blog_snippets else '(블로그 리뷰 없음)'}

작성 가이드:
- 자연스러운 1인칭 후기 형식
- 사진 위치를 [사진1], [사진2] 등으로 표시
- 핵심 키워드를 본문에 자연스럽게 포함 (업체명, 지역, 카테고리)
- 800~1500자 분량
- 해시태그 3개 제안
- SEO/AEO/GEO 최적화: 업체명과 지역명을 제목과 본문 앞부분에 배치"""

    return {
        "title": title,
        "body": "\n".join(sections),
        "aiPrompt": ai_prompt,
        "images": images,
        "placeData": {
            "name": name,
            "category": category,
            "address": address,
            "phone": phone,
            "menuCount": len(menus),
            "reviewCount": review_count,
            "blogReviewCount": blog_review_count,
            "keywordCount": len(keywords),
            "imageCount": len(images),
        },
    }


def _is_naver_image(src: str) -> bool:
    """네이버 CDN 이미지 URL인지 확인"""
    return any(p in src for p in ("pstatic.net", "blogfiles", "postfiles", "naver.net"))


def _extract_images(content_tag) -> list[str]:
    """블로그 본문에서 모든 이미지 URL 추출

    3가지 소스를 탐색:
    1) img 태그 — data-lazy-src > data-src > src (lazy-load 대응)
    2) a[data-linkdata] — se-imageGroup(콜라주/슬라이드)에 숨겨진 원본 이미지
    3) background-image style — 일부 구 에디터 또는 커스텀 템플릿
    """
    seen = set()
    images = []

    def _add(src: str):
        if src and src.startswith("http") and src not in seen:
            # 네이버 CDN이거나, 네이버 프록시를 경유한 외부 이미지
            if _is_naver_image(src):
                seen.add(src)
                images.append(src)

    # 1) img 태그
    for img in content_tag.find_all("img"):
        src = (
            img.get("data-lazy-src")
            or img.get("data-src")
            or img.get("src")
            or ""
        )
        _add(src)

    # 2) a[data-linkdata] — se-imageGroup 내부의 숨겨진 이미지
    #    콜라주/슬라이드/링크복사 이미지는 img 태그 없이 data-linkdata에만 존재
    for a_tag in content_tag.find_all("a", attrs={"data-linkdata": True}):
        try:
            linkdata = json.loads(a_tag["data-linkdata"])
            src = linkdata.get("src", "")
            _add(src)
        except (json.JSONDecodeError, KeyError):
            continue

    # 3) background-image style (구 에디터 일부)
    for el in content_tag.find_all(style=True):
        style = el.get("style", "")
        if "background" in style and "url(" in style:
            match = re.search(r'url\(["\']?(https?://[^"\')]+)', style)
            if match:
                _add(match.group(1))

    return images
