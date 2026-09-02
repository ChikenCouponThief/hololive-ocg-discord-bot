import os
import re
import json
import requests


USERNAME = "hololive_OCG"
LAST_POST_FILE = "last_post.txt"

TIMELINE_URL = (
    f"https://syndication.twitter.com/"
    f"srv/timeline-profile/screen-name/{USERNAME}"
)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def load_last_post():
    if not os.path.exists(LAST_POST_FILE):
        return None

    with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
        return file.read().strip()


def save_last_post(post_id):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
        file.write(post_id)


def get_timeline_data():
    print("X Syndication 타임라인 확인 중...")
    print(TIMELINE_URL)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/142.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml"
    }

    response = requests.get(
        TIMELINE_URL,
        headers=headers,
        timeout=15
    )

    print("응답 코드:", response.status_code)

    if response.status_code != 200:
        raise Exception(
            f"X Syndication 서버 오류: {response.status_code}"
        )

    html = response.text

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL
    )

    if not match:
        raise Exception(
            "X 타임라인 데이터(__NEXT_DATA__)를 찾지 못했습니다."
        )

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise Exception(
            f"X 타임라인 JSON 분석 실패: {error}"
        )

    return data


def find_status_ids(obj):
    status_ids = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():

                # 흔히 사용되는 Tweet ID 필드
                if key in [
                    "id_str",
                    "tweetId",
                    "tweet_id",
                    "rest_id"
                ]:
                    text = str(item)

                    if text.isdigit() and len(text) >= 15:
                        status_ids.append(text)

                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

        elif isinstance(value, str):

            # URL 안의 /status/숫자도 탐색
            matches = re.findall(
                r"/status/(\d+)",
                value
            )

            status_ids.extend(matches)

    walk(obj)

    return status_ids


def get_latest_post_id():
    data = get_timeline_data()

    ids = find_status_ids(data)

    if not ids:
        raise Exception(
            "X 타임라인에서 게시글 ID를 찾지 못했습니다."
        )

    # Snowflake ID는 대체로 숫자가 클수록 최신
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
        raise Exception(
            "DISCORD_WEBHOOK_URL Secret이 설정되지 않았습니다."
        )

    message = {
        "content": (
            "📢 **hololive OCG 새로운 게시글**\n\n"
            f"{post_link}"
        )
    }

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json=message,
        timeout=15
    )

    print("Discord 응답 코드:", response.status_code)

    if response.status_code not in [200, 204]:
        raise Exception(
            f"Discord 전송 실패: {response.status_code}"
        )

    print("Discord 전송 성공!")


def main():
    print("==============================")
    print(" Hololive OCG Discord Bot")
    print("==============================")
    print()

    current_post_id = get_latest_post_id()

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

    # 새 글 없음
    if current_post_id == last_post_id:
        print()
        print("새로운 게시글이 없습니다.")
        return

    # 새 글 발견
    print()
    print("새로운 게시글 발견!")

    post_link = make_x_link(current_post_id)

    print("게시글 링크:")
    print(post_link)

    send_to_discord(post_link)

    save_last_post(current_post_id)

    print()
    print("last_post.txt 업데이트 완료")


if __name__ == "__main__":
    main()
