import os
import re
import requests
import feedparser


USERNAME = "hololive_OCG"
LAST_POST_FILE = "last_post.txt"

# 여러 RSSHub 서버를 순서대로 시도
RSS_URLS = [
    f"https://rsshub.stsecurity.moe/twitter/user/{USERNAME}/exclude_rts_replies",
    f"https://rsshub.yfi.moe/twitter/user/{USERNAME}/exclude_rts_replies",
    f"https://rss.con.sh/twitter/user/{USERNAME}/exclude_rts_replies",
]

webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")


def get_post_id(link):
    match = re.search(r"/status/(\d+)", link)

    if match:
        return match.group(1)

    return None


def convert_to_x_link(link):
    post_id = get_post_id(link)

    if post_id:
        return f"https://x.com/{USERNAME}/status/{post_id}"

    return link


def load_last_post():
    if not os.path.exists(LAST_POST_FILE):
        return None

    with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
        return file.read().strip()


def save_last_post(post_id):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
        file.write(post_id)


def send_to_discord(post_link):
    if not webhook_url:
        raise Exception("DISCORD_WEBHOOK_URL이 설정되지 않았습니다.")

    message = {
        "content": (
            "📢 **hololive OCG 새로운 게시글**\n\n"
            f"{post_link}"
        )
    }

    response = requests.post(
        webhook_url,
        json=message,
        timeout=20
    )

    if response.status_code not in [200, 204]:
        raise Exception(
            f"Discord 전송 실패: {response.status_code}"
        )

    print("Discord 전송 성공!")


def get_feed():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for rss_url in RSS_URLS:
        print()
        print("RSS 서버 확인:")
        print(rss_url)

        try:
            response = requests.get(
                rss_url,
                headers=headers,
                timeout=20
            )

            print("응답 코드:", response.status_code)

            if response.status_code != 200:
                print("이 서버는 사용할 수 없습니다.")
                continue

            feed = feedparser.parse(response.content)

            if not feed.entries:
                print("게시글이 없습니다.")
                continue

            print("RSS 서버 연결 성공!")
            return feed

        except Exception as error:
            print("RSS 서버 오류:")
            print(error)

    raise Exception(
        "사용 가능한 RSS 서버를 찾지 못했습니다."
    )


def main():
    print("==============================")
    print("Hololive OCG Discord Bot")
    print("==============================")

    print()
    print("hololive_OCG 게시글 확인 중...")

    feed = get_feed()

    latest_post = feed.entries[0]

    current_post_id = get_post_id(latest_post.link)

    if not current_post_id:
        raise Exception(
            f"게시글 ID를 찾지 못했습니다: {latest_post.link}"
        )

    last_post_id = load_last_post()

    print()
    print("저장된 게시글:", last_post_id)
    print("현재 게시글:", current_post_id)

    if last_post_id == current_post_id:
        print("새로운 게시글이 없습니다.")
        return

    print()
    print("새로운 게시글 발견!")

    x_link = convert_to_x_link(latest_post.link)

    print("X 링크:")
    print(x_link)

    send_to_discord(x_link)

    save_last_post(current_post_id)

    print()
    print("last_post.txt 업데이트 완료")


if __name__ == "__main__":
    main()
