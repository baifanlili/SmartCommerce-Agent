import re

from smart_commerce.models.schemas import ShoppingFilters, ShoppingIntent


_CATEGORY_MAP = {
    "笔记本": "Laptop",
    "电脑": "Laptop",
    "手机": "Phone",
    "耳机": "Audio",
    "显示器": "Monitor",
}
_PREFERENCE_KEYWORDS = ("程序员", "游戏", "办公", "便携", "摄影", "学生")


def parse_shopping_intent(message: str) -> ShoppingIntent:
    """Build the deterministic intent used by the Mock fallback path."""
    return ShoppingIntent(
        raw_message=message,
        filters=ShoppingFilters(
            max_price=_extract_budget(message),
            category=_extract_category(message),
            keywords=[keyword for keyword in _PREFERENCE_KEYWORDS if keyword in message],
        ),
    )


def _extract_budget(message: str) -> float | None:
    match = re.search(r"(?:低于|不超过|预算|不高于)\s*[¥￥]?\s*(\d+(?:\.\d+)?)", message)
    if not match:
        match = re.search(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|以下|封顶)", message)
    if not match:
        match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", message)
    return float(match.group(1)) if match else None


def _extract_category(message: str) -> str | None:
    for keyword, category in _CATEGORY_MAP.items():
        if keyword in message:
            return category
    return None
