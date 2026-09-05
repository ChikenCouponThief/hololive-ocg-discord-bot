import os
import re
import json
import time
import random
import requests


USERNAME = "hololive_OCG"
LAST_POST_FILE = "last_post.txt"

TIMELINE_URL = (
    f"https://syndication.twitter.com/"
    f"srv/timeline-profile/screen-name/{USERNAME}"
)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
BASE_RETRY_WAIT = 20


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/142.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def load_last_post():
    if not os.path.exists(LAST_POST_FILE):
        return None

    try:
        with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError as error:
        print(f"last_post.txt 읽기 실패: {error}")
        return None


def save_last_post(post_id):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
        file.write(str(post_id))


def get_timeline_data():
    print("X Syndication 타임라인 확인 중...")
    print(TIMELINE_URL)

    session = requests.Session()
    session.headers.update(HEADERS)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                TIMELINE_URL,
                timeout=REQUEST_TIMEOUT,
            )

            print("응답 코드:", response.status_code)

            if response.status_code == 200:
                html = response.text

                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html,
                    re.DOTALL,
                )

                if not match:
                    print("X 타임라인 데이터(__NEXT_DATA__)를 찾지 못했습니다.")
                    return None

                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError as error:
                    print(f"X 타임라인 JSON 분석 실패: {error}")
                    return None

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                if retry_after:
                    try:
                        wait_time = max(int(retry_after), 1)
                    except ValueError:
                        wait_time = BASE_RETRY_WAIT * attempt
                else:
                    wait_time = BASE_RETRY_WAIT * attempt

                # 여러 GitHub Actions 실행이 같은 순간에
                # 재시도하는 것을 조금 피함
                wait_time += random.randint(1, 5)

                print(
                    f"X 요청 제한(429) 발생: "
                    f"{attempt}/{MAX_RETRIES}회"
                )

                if attempt < MAX_RETRIES:
                    print(f"{wait_time}초 후 재시도합니다.")
                    time.sleep(wait_time)
                    continue

                print("429가 계속되어 이번 실행은 건너뜁니다.")
                return None

            if 500 <= response.status_code <= 599:
                wait_time = 10 * attempt

                print(
                    f"X 서버 오류({response.status_code}) 발생: "
                    f"{attempt}/{MAX_RETRIES}회"
                )

                if attempt < MAX_RETRIES:
                    print(f"{wait_time}초 후 재시도합니다.")
                    time.sleep(wait_time)
                    continue

                print("X 서버 오류가 계속되어 이번 실행은 건너뜁니다.")
                return None

            print(
                f"X Syndication 서버 오류: {response.status_code}. "
                "이번 실행은 건너뜁니다."
            )
            return None

        except requests.exceptions.Timeout:
            wait_time = 10 * attempt

            print(
                f"X 요청 시간 초과: {attempt}/{MAX_RETRIES}회"
            )

            if attempt < MAX_RETRIES:
                print(f"{wait_time}초 후 재시도합니다.")
                time.sleep(wait_time)
                continue

            print("요청 시간 초과가 계속되어 이번 실행은 건너뜁니다.")
            return None

        except requests.exceptions.RequestException as error:
            wait_time = 10 * attempt

            print(
                f"X 네트워크 오류: {attempt}/{MAX_RETRIES}회 - {error}"
            )

            if attempt < MAX_RETRIES:
                print(f"{wait_time}초 후 재시도합니다.")
                time.sleep(wait_time)
                continue

            print("네트워크 오류가 계속되어 이번 실행은 건너뜁니다.")
            return None

    return None


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
            matches = re.findall(
                r"/status/(\d+)",
                value,
            )

            status_ids.extend(matches)

    walk(obj)

    return status_ids


def get_latest_post_id():
    data = get_timeline_data()

    if data is None:
        return None

    ids = find_status_ids(data)

    if not ids:
        print("X 타임라인에서 게시글 ID를 찾지 못했습니다.")
        return None

    # Snowflake ID는 숫자가 클수록 일반적으로 최신
    ids = list(set(ids))
    ids.sort(key=int, reverse=True)

    print("발견된 게시글 ID 수:", len(ids))

    latest_id = ids[0]

    print("최신 게시글 ID:", latest_id)

    return latest_id


def make_x_link(post_id):
    return (
        f"https://x.com/"
        f"{USERNAME}/status/{post_id}"
    )


def send_to_discord(post_link):
    if not DISCORD_WEBHOOK_URL:
        print(
            "DISCORD_WEBHOOK_URL Secret이 "
            "설정되지 않았습니다."
        )
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

    except requests.exceptions.RequestException as error:
        print(f"Discord 요청 오류: {error}")
        return False

    print("Discord 응답 코드:", response.status_code)

    if response.status_code not in [200, 204]:
        print(
            f"Discord 전송 실패: "
            f"{response.status_code}"
        )

        print(response.text[:500])

        return False

    print("Discord 전송 성공!")

    return True


def main():
    print("==============================")
    print(" Hololive OCG Discord Bot")
    print("==============================")
    print()

    current_post_id = get_latest_post_id()

    # X가 429/서버 오류/Timeout 등으로 실패해도
    # GitHub Actions 자체는 실패시키지 않음
    if current_post_id is None:
        print()
        print("최신 게시글 확인에 실패했습니다.")
        print(
            "이번 실행은 건너뛰고 "
            "다음 GitHub Actions 실행에서 다시 확인합니다."
        )
        return

    last_post_id = load_last_post()

    print()
    print("저장된 게시글 ID:", last_post_id)
    print("현재 최신 게시글 ID:", current_post_id)

    # 처음 실행
    if not last_post_id:
        print()
        print("last_post.txt가 비어 있습니다.")
        print("현재 게시글을 기준점으로 저장합니다.")

        save_last_post(current_post_id)

        return

    # ID 형식 확인
    if not current_post_id.isdigit() or not last_post_id.isdigit():
        print()
        print("게시글 ID 형식이 올바르지 않습니다.")
        print(
            "이번 실행에서는 "
            "last_post.txt를 변경하지 않습니다."
        )
        return

    current_num = int(current_post_id)
    last_num = int(last_post_id)

    # 새 글 없음
    if current_num <= last_num:
        print()
        print("새로운 게시글이 없습니다.")
        return

    # 새 글 발견
    print()
    print("새로운 게시글 발견!")

    post_link = make_x_link(current_post_id)

    print("게시글 링크:")
    print(post_link)

    # Discord 전송 성공 시에만 last_post.txt 갱신
    if not send_to_discord(post_link):
        print()
        print("Discord 전송에 실패했습니다.")
        print("last_post.txt는 변경하지 않습니다.")
        print("다음 실행에서 다시 전송을 시도합니다.")
        return

    save_last_post(current_post_id)

    print()
    print("last_post.txt 업데이트 완료")


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print()
        print("예상하지 못한 오류가 발생했습니다.")
        print(
            f"{type(error).__name__}: {error}"
        )
