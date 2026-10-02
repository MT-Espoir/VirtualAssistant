"""Explicit local webcam commands handled after the voice intent/wake-word gate."""

import re

from utils.text_norm import norm


_OFF_COMMAND = re.compile(
    r"(?:(?:hay|vui long|lam on) )?"
    r"(?:tat|ngung|dung|tam dung) "
    r"(?:web ?cam|camera(?: webcam| may tinh| laptop)?)"
    r"(?: (?:di|nhe|nha|giup (?:toi|minh|anh|em)))*")


def match_camera_command(text, wake_words=()):
    """Match a complete imperative; questions/negations/multi-action text fall through."""
    normalized = " ".join(norm(text).split())
    # In work/follow-up/text mode the main loop can retain a spoken assistant name.
    # Remove configured names only at the start; preserve negation in the sentence.
    names = sorted((" ".join(norm(word).split()) for word in wake_words),
                   key=len, reverse=True)
    for name in names:
        if name and re.match(re.escape(name) + r"[\s,.!?:;]+", normalized):
            normalized = re.sub(re.escape(name) + r"[\s,.!?:;]+", "", normalized, count=1)
            break
    return "off" if _OFF_COMMAND.fullmatch(normalized) else None


def extract_camera_off_command(text, wake_words=()):
    """Extract only an independent off clause; preserve remaining clause content.

    Do not split conditional, negated, quoted or explicitly ordered instructions.
    These remain with the Agent, which has a dedicated webcam tool.
    """
    if any(mark in text for mark in ('"', "“", "”", "'", "‘", "’")):
        return False, text
    if match_camera_command(text, wake_words) == "off":
        return True, ""
    normalized = norm(text)
    if re.search(r"\b(?:khong|dung|neu|khi|he|chua|tru|roi|sau|truoc)\b", normalized):
        return False, text
    clauses = re.split(r"\s+(?:và|va)\s+|[,;]\s*", text, flags=re.IGNORECASE)
    if len(clauses) < 2:
        return False, text
    remaining = []
    found = False
    for clause in clauses:
        if match_camera_command(clause.strip(), wake_words) == "off":
            found = True
        elif clause.strip():
            remaining.append(clause.strip())
    return (True, "; ".join(remaining)) if found else (False, text)


def turn_off_webcam(camera):
    """Use the existing pause lifecycle: release capture and invalidate consumers."""
    if camera is None:
        return "Webcam của Alice hiện không được bật."
    camera.pause()
    return "Đã tắt webcam."
