"""Messages to users: the links that reset a password (H32).

No SMS provider or mail server is chosen yet, so every message goes to a local outbox: one HTML file per
message in the git-ignored local/outbox/, opened like a received SMS or email, whose link opens the
client (mbs://). The server's window names each new file. Nothing leaves the PC, and the files are not
logged anywhere else, since each holds a working link.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .config import REPOSITORY
from .models import SMS

OUTBOX = REPOSITORY / "local" / "outbox"
RESET_LINK = "mbs://reset-password"  # the client's own link type (H32)

TEXTS = {
    "en": {
        "sms": ("Identification System: to choose a new password, open this link within {minutes} minutes. "
                "It works once.", "If you did not ask for this, ignore this message."),
        "subject": "Choose a new password",
        "email": ("Hello {username},",
                  "Someone asked to choose a new password for your account in the Identification System. "
                  "To choose one, open this link within {minutes} minutes. It works once:",
                  "If you did not ask for this, ignore this email. Your password stays as it is."),
        "to": "To",
        "sms_kind": "SMS",
        "email_kind": "Email",
    },
    "he": {
        "sms": ("מערכת הזיהוי: כדי לבחור סיסמה חדשה, פותחים את הקישור תוך {minutes} דקות. הוא עובד פעם אחת.",
                "אם לא ביקשת, אפשר להתעלם מההודעה."),
        "subject": "בחירת סיסמה חדשה",
        "email": ("שלום {username},",
                  "התקבלה בקשה לבחור סיסמה חדשה לחשבון שלך במערכת הזיהוי. כדי לבחור אותה, פותחים את הקישור "
                  "הזה תוך {minutes} דקות. הקישור עובד פעם אחת:",
                  "אם לא ביקשת, אפשר להתעלם מהאימייל. הסיסמה שלך נשארת כמו שהיא."),
        "to": "אל",
        "sms_kind": "מסרון",
        "email_kind": "אימייל",
    },
}


@dataclass(frozen=True)
class Message:
    """One message, in the language of the screen that asked for it: the text before the link and after it."""

    channel: str  # sms or email
    to: str  # the account's phone (E.164) or email, never what was typed in the request
    language: str
    subject: str | None
    before: tuple[str, ...]
    link: str
    after: tuple[str, ...]

    @property
    def text(self) -> str:
        """The message as an SMS would carry it."""
        return "\n".join((*self.before, self.link, *self.after))


def password_reset(channel: str, to: str, username: str, token: str, language: str, minutes: int) -> Message:
    texts = TEXTS[language]
    link = f"{RESET_LINK}?{urlencode({'token': token, 'lang': language})}"
    if channel == SMS:
        first, last = texts["sms"]
        return Message(channel, to, language, None, (first.format(minutes=minutes),), link, (last,))
    greeting, body, last = texts["email"]
    return Message(channel, to, language, texts["subject"],
                   (greeting.format(username=username), body.format(minutes=minutes)), link, (last,))


class Outbox:
    def __init__(self, folder: Path = OUTBOX):
        self.folder = folder

    def send(self, message: Message) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        moment = datetime.now(timezone.utc)
        path = self.folder / f"{moment:%Y%m%d-%H%M%S-%f}-{message.channel}.html"
        path.write_text(_page(message, moment), encoding="utf-8", newline="\n")
        print(f"outbox: a new {'SMS' if message.channel == SMS else 'email'} message is in {path}", flush=True)
        return path


def _page(message: Message, moment: datetime) -> str:
    texts = TEXTS[message.language]
    kind = texts["sms_kind" if message.channel == SMS else "email_kind"]
    paragraphs = "\n".join(f"<p>{html.escape(p)}</p>" for p in message.before)
    paragraphs += f'\n<p class="link"><a href="{html.escape(message.link)}">{html.escape(message.link)}</a></p>\n'
    paragraphs += "\n".join(f"<p>{html.escape(p)}</p>" for p in message.after)
    subject = f"<h1>{html.escape(message.subject)}</h1>\n" if message.subject else ""
    return f"""<!doctype html>
<html lang="{message.language}" dir="{'rtl' if message.language == 'he' else 'ltr'}">
<head>
<meta charset="utf-8">
<title>{html.escape(message.subject or kind)}</title>
<style>
body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem;
       line-height: 1.5; color: #1b1f24; background: #f6f7f9; }}
.message {{ padding: 1.25rem 1.5rem; border: 1px solid #d9dde3; border-radius: 12px; background: #fff; }}
.meta {{ margin: 0 0 1rem; color: #5b6470; font-size: 0.9rem; }}
h1 {{ font-size: 1.2rem; margin: 0 0 1rem; }}
.link {{ direction: ltr; text-align: left; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<div class="message">
<p class="meta">{html.escape(kind)} · {html.escape(texts['to'])}: <bdi>{html.escape(message.to)}</bdi> · {moment:%Y-%m-%d %H:%M} UTC</p>
{subject}{paragraphs}
</div>
</body>
</html>
"""
