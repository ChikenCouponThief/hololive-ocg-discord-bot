import os
import re
import requests
import feedparser

RSS_URL = "https://nitter.net/hololive_OCG/rss"
LAST_POST_FILE = "last_post.txt"

webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")


def get_post_id(link):
    match = re.search(r"/status/(\d+)", link)

    if match:
        return match.group(1)

    return None


def convert_to_x_link(link):
    post_id = get_post_id(link)

    if post_id:
        return f"https://x.com/hololive_OCG/status/{post_id}"

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
        timeout=15
    )

    if response.status_code not in [200, 204]:
        raise Exception(
            f"Discord 전송 실패: {response.status_code}"
        )

    print("Discord 전송 성공!")


def main():
    print("hololive_OCG 게시글 확인 중...")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(
        RSS_URL,
        headers=headers,
        timeout=15
    )

    if response.status_code != 200:
        raise Exception(
            f"RSS 서버 오류: {response.status_code}"
        )

    feed = feedparser.parse(response.content)

    if not feed.entries:
        raise Exception("게시글을 찾지 못했습니다.")

    latest_post = feed.entries[0]

    current_post_id = get_post_id(latest_post.link)

    if not current_post_id:
        raise Exception("게시글 ID를 찾지 못했습니다.")

    last_post_id = load_last_post()

    print("저장된 게시글:", last_post_id)
    print("현재 게시글:", current_post_id)

    if last_post_id == current_post_id:
        print("새로운 게시글이 없습니다.")
        return

    print("새로운 게시글 발견!")

    x_link = convert_to_x_link(latest_post.link)

    print(x_link)

    send_to_discord(x_link)

    save_last_post(current_post_id)


if __name__ == "__main__":
    main()
