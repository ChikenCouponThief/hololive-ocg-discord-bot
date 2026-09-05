import os
import re
import json
import time
import random
import html
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests


# ============================================================
# 기본 설정
# ============================================================

USERNAME = "hololive_OCG"
LAST_POST_FILE = "last_post.txt"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

REQUEST_TIMEOUT = 15

# 한 소스에서 지나치게 오래 붙잡히지 않도록 짧게 재시도
MAX_RETRIES_PER_SOURCE = 2

# Nitter 인스턴스 목록을 매 실행마다 가져오는 공개 목록
LIBREDIRECT_INSTANCES_URL = (
    "https://raw.githubusercontent.com/libredirect/instances/main/data.json"
)

# 공개 목록 조회 자체가 실패했을 때 사용할 기본 후보
BUILTIN_NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://nuku.trabun.org",
    "https://nitter.catsarch.com",
    "https://nitter.kareem.one",
]

# 기존 방식은 최후의 fallback으로만 유지
SYNDICATION_URL = (
    f"https://syndication.twitter.com/"
    f"srv/timeline-profile/screen-name/{USERNAME}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml,"
        "application/rss+xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================
# 로그
# ============================================================

def log(*args):
    # GitHub Actions에서 실시간으로 바로 보이도록 flush
    print(*args, flush=True)


# ============================================================
# last_post.txt
# ============================================================

def load_last_post():
    if not os.path.exists(LAST_POST_FILE):
        return None

    try:
        with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
            value = file.read().strip()

        if value and value.isdigit():
            return value

        if value:
            log("last_post.txt 값이 숫자가 아닙니다:", value)

        return None

    except OSError as error:
        log("last_post.txt 읽기 실패:", error)
        return None


def save_last_post(post_id):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
        file.write(str(post_id))


# ============================================================
# 공통 유틸
# ============================================================

def extract_status_id(text):
    if not text:
        return None

    patterns = [
        r"(?:x|twitter)\.com/[^/\s]+/status/(\d+)",
        r"/status/(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def normalize_instance(url):
    return url.rstrip("/")


def unique_keep_order(items):
    seen = set()
    result = []

    for item in items:
        if not item:
            continue

        item = normalize_instance(item)

        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


# ============================================================
# Nitter 인스턴스 목록
# ============================================================

def get_nitter_instances():
    candidates = []

    log("공개 Nitter 인스턴스 목록 확인 중...")

    try:
        response = requests.get(
            LIBREDIRECT_INSTANCES_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        log("Nitter 목록 응답 코드:", response.status_code)

        if response.status_code == 200:
            data = response.json()

            nitter = data.get("nitter", {})
            clearnet = nitter.get("clearnet", [])

            if isinstance(clearnet, list):
                candidates.extend(clearnet)

    except Exception as error:
        log("Nitter 공개 목록 확인 실패:", error)

    candidates.extend(BUILTIN_NITTER_INSTANCES)

    result = unique_keep_order(candidates)

    # 무한정 많은 인스턴스를 돌지 않게 제한
    result = result[:12]

    log("사용할 Nitter 후보 수:", len(result))

    return result


# ============================================================
# Nitter RSS 방식
# ============================================================

def parse_nitter_rss(xml_text):
    ids = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for item in root.findall(".//item"):
        link = item.findtext("link") or ""
        guid = item.findtext("guid") or ""
        title = item.findtext("title") or ""
        description = item.findtext("description") or ""

        for value in [link, guid, title, description]:
            post_id = extract_status_id(html.unescape(value))
            if post_id and post_id.isdigit():
                ids.append(post_id)

    return ids


def get_latest_from_nitter_rss():
    instances = get_nitter_instances()

    for index, instance in enumerate(instances, start=1):
        rss_url = f"{instance}/{USERNAME}/rss"

        log()
        log(f"[Nitter RSS {index}/{len(instances)}]")
        log(rss_url)

        try:
            response = requests.get(
                rss_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            log("응답 코드:", response.status_code)

            if response.status_code != 200:
                continue

            content_type = response.headers.get("Content-Type", "").lower()

            # 일부 인스턴스는 Cloudflare/차단 HTML을 200으로 돌려주므로
            # 실제 RSS 구조가 맞는지 함께 검사
            text = response.text

            if (
                "<rss" not in text[:1000].lower()
                and "<feed" not in text[:1000].lower()
                and "xml" not in content_type
                and "rss" not in content_type
            ):
                log("RSS가 아닌 응답입니다. 다음 인스턴스로 이동합니다.")
                continue

            ids = parse_nitter_rss(text)

            if not ids:
                log("게시글 ID를 찾지 못했습니다.")
                continue

            ids = sorted(set(ids), key=int, reverse=True)
            latest_id = ids[0]

            log("Nitter RSS 조회 성공")
            log("발견된 게시글 ID 수:", len(ids))
            log("최신 게시글 ID:", latest_id)

            return latest_id

        except requests.exceptions.Timeout:
            log("Timeout. 다음 인스턴스로 이동합니다.")

        except requests.exceptions.RequestException as error:
            log("요청 오류:", error)

        except Exception as error:
            log("처리 오류:", error)

    return None


# ============================================================
# Nitter HTML 방식
# RSS를 막아둔 인스턴스도 있어서 두 번째 방식으로 검사
# ============================================================

def get_latest_from_nitter_html():
    instances = get_nitter_instances()

    for index, instance in enumerate(instances, start=1):
        profile_url = f"{instance}/{USERNAME}"

        log()
        log(f"[Nitter HTML {index}/{len(instances)}]")
        log(profile_url)

        try:
            response = requests.get(
                profile_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            log("응답 코드:", response.status_code)

            if response.status_code != 200:
                continue

            text = response.text

            # 프로필 페이지에서 해당 사용자의 status URL만 찾음
            patterns = [
                rf"/{re.escape(USERNAME)}/status/(\d+)",
                rf"https?://(?:x|twitter)\.com/{re.escape(USERNAME)}/status/(\d+)",
            ]

            ids = []

            for pattern in patterns:
                ids.extend(
                    re.findall(
                        pattern,
                        text,
                        flags=re.IGNORECASE,
                    )
                )

            if not ids:
                log("게시글 ID를 찾지 못했습니다.")
                continue

            ids = sorted(set(ids), key=int, reverse=True)
            latest_id = ids[0]

            log("Nitter HTML 조회 성공")
            log("발견된 게시글 ID 수:", len(ids))
            log("최신 게시글 ID:", latest_id)

            return latest_id

        except requests.exceptions.Timeout:
            log("Timeout. 다음 인스턴스로 이동합니다.")

        except requests.exceptions.RequestException as error:
            log("요청 오류:", error)

        except Exception as error:
            log("처리 오류:", error)

    return None


# ============================================================
# X Syndication 기존 방식
# 최후 fallback
# ============================================================

def find_status_ids(obj):
    status_ids = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in [
                    "id_str",
                    "tweetId",
                    "tweet_id",
                    "rest_id",
                ]:
                    text = str(item)

                    if text.isdigit() and len(text) >= 15:
                        status_ids.append(text)

                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

        elif isinstance(value, str):
            matches = re.findall(r"/status/(\d+)", value)
            status_ids.extend(matches)

    walk(obj)
    return status_ids


def get_latest_from_syndication():
    log()
    log("[X Syndication fallback]")
    log(SYNDICATION_URL)

    for attempt in range(1, MAX_RETRIES_PER_SOURCE + 1):
        try:
            response = requests.get(
                SYNDICATION_URL,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            log("응답 코드:", response.status_code)

            if response.status_code == 200:
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    response.text,
                    re.DOTALL,
                )

                if not match:
                    log("__NEXT_DATA__를 찾지 못했습니다.")
                    return None

                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError as error:
                    log("JSON 분석 실패:", error)
                    return None

                ids = find_status_ids(data)

                if not ids:
                    log("게시글 ID를 찾지 못했습니다.")
                    return None

                ids = sorted(set(ids), key=int, reverse=True)

                log("Syndication 조회 성공")
                log("최신 게시글 ID:", ids[0])

                return ids[0]

            if response.status_code == 429:
                log(
                    f"X 요청 제한(429): "
                    f"{attempt}/{MAX_RETRIES_PER_SOURCE}"
                )

                if attempt < MAX_RETRIES_PER_SOURCE:
                    wait_time = 5 + random.randint(1, 5)
                    log(f"{wait_time}초 후 한 번 더 시도합니다.")
                    time.sleep(wait_time)
                    continue

                return None

            if 500 <= response.status_code <= 599:
                if attempt < MAX_RETRIES_PER_SOURCE:
                    time.sleep(5)
                    continue

                return None

            return None

        except requests.exceptions.RequestException as error:
            log("Syndication 요청 오류:", error)

            if attempt < MAX_RETRIES_PER_SOURCE:
                time.sleep(5)
                continue

            return None

    return None


# ============================================================
# 최신 게시글 조회
# ============================================================

def get_latest_post_id():
    log("==============================")
    log(" X 게시글 조회 시작")
    log("==============================")

    # 1순위: 여러 공개 Nitter의 RSS
    post_id = get_latest_from_nitter_rss()

    if post_id:
        log()
        log("사용된 조회 방식: Nitter RSS")
        return post_id

    log()
    log("Nitter RSS 전부 실패")

    # 2순위: 여러 공개 Nitter의 HTML
    post_id = get_latest_from_nitter_html()

    if post_id:
        log()
        log("사용된 조회 방식: Nitter HTML")
        return post_id

    log()
    log("Nitter HTML 전부 실패")

    # 3순위: 기존 Syndication
    post_id = get_latest_from_syndication()

    if post_id:
        log()
        log("사용된 조회 방식: X Syndication")
        return post_id

    log()
    log("모든 X 게시글 조회 방식이 실패했습니다.")

    return None


# ============================================================
# Discord
# ============================================================

def make_x_link(post_id):
    return f"https://x.com/{USERNAME}/status/{post_id}"


def send_to_discord(post_link):
    if not DISCORD_WEBHOOK_URL:
        log("DISCORD_WEBHOOK_URL Secret이 설정되지 않았습니다.")
        return False

    message = {
        "content": (
            "📢 **hololive OCG 새로운 게시글**\n\n"
            f"{post_link}"
        )
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            timeout=REQUEST_TIMEOUT,
        )

        log("Discord 응답 코드:", response.status_code)

        if response.status_code not in [200, 204]:
            log("Discord 전송 실패")
            log(response.text[:500])
            return False

        log("Discord 전송 성공!")
        return True

    except requests.exceptions.RequestException as error:
        log("Discord 요청 오류:", error)
        return False


# ============================================================
# 메인
# ============================================================

def main():
    log("==============================")
    log(" Hololive OCG Discord Bot")
    log("==============================")
    log()

    current_post_id = get_latest_post_id()

    if current_post_id is None:
        log()
        log("최신 게시글 확인에 실패했습니다.")
        log("last_post.txt는 변경하지 않습니다.")
        log("이번 실행은 정상 종료하고 다음 예약 실행에서 다시 확인합니다.")
        return

    last_post_id = load_last_post()

    log()
    log("저장된 게시글 ID:", last_post_id)
    log("현재 최신 게시글 ID:", current_post_id)

    # 처음 실행
    if not last_post_id:
        log()
        log("last_post.txt가 비어 있습니다.")
        log("현재 게시글을 기준점으로 저장합니다.")

        save_last_post(current_post_id)
        return

    if not current_post_id.isdigit() or not last_post_id.isdigit():
        log()
        log("게시글 ID 형식이 올바르지 않습니다.")
        log("last_post.txt는 변경하지 않습니다.")
        return

    current_num = int(current_post_id)
    last_num = int(last_post_id)

    if current_num <= last_num:
        log()
        log("새로운 게시글이 없습니다.")
        return

    log()
    log("새로운 게시글 발견!")

    post_link = make_x_link(current_post_id)

    log("게시글 링크:")
    log(post_link)

    # Discord 전송에 성공해야만 기준점을 앞으로 이동
    if not send_to_discord(post_link):
        log()
        log("Discord 전송에 실패했습니다.")
        log("last_post.txt는 변경하지 않습니다.")
        log("다음 실행에서 다시 전송을 시도합니다.")
        return

    save_last_post(current_post_id)

    log()
    log("last_post.txt 업데이트 완료")


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        # 예약 실행 전체를 죽이지는 않되 원인은 로그에 남김
        log()
        log("예상하지 못한 오류가 발생했습니다.")
        log(f"{type(error).__name__}: {error}")
