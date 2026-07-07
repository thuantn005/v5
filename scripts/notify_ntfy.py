"""
notify_ntfy.py
---------------
Sends a push notification to an ntfy.sh topic.

Usage:
    python notify_ntfy.py --topic lotto535-thuan --title "..." --message "..." [--priority default] [--tags tag1,tag2]
"""

import argparse
import sys
import requests


def send(topic: str, title: str, message: str, priority: str = "default", tags: str = ""):
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags
    resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)
    resp.raise_for_status()
    print(f"Notification sent to ntfy.sh/{topic} (status {resp.status_code})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--priority", default="default")
    parser.add_argument("--tags", default="")
    args = parser.parse_args()

    try:
        send(args.topic, args.title, args.message, args.priority, args.tags)
    except requests.RequestException as e:
        print(f"ERROR sending notification: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
