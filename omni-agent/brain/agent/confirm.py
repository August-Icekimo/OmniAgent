"""確認往返的同意／取消判斷與回覆選項（reply-quick-options）。

舊判斷是子字串比對（`"好" in text`），「不好」「不可以」「好像怪怪的」都會被當成同意。
改為「整句」比對：去掉空白與標點後必須完全等於同意詞／取消詞之一。
按鈕送出的文字（CONFIRM_OPTIONS 的 text）必定落在對應詞組內。
"""

import re

# 點按後以使用者身分送出的文字；label 是按鈕上顯示的字。
# LINE Quick Reply label ≤ 20 字、Telegram callback_data ≤ 64 bytes，皆遠低於上限。
CONFIRM_OPTIONS = [
    {"label": "好，繼續", "text": "好"},
    {"label": "取消", "text": "取消"},
]

CANCELLED_REPLY = "好，已取消。"

_AFFIRMATIVE = {"好", "好的", "好啊", "好喔", "可以", "確認", "繼續", "yes", "y", "ok", "okay", "go"}
_CANCEL = {"取消", "不要", "不用", "不用了", "算了", "no", "n", "cancel"}

# 空白、全半形標點、常見語氣符號與 emoji 以外的裝飾（保留文字與數字）
_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize(text: str | None) -> str:
    return _STRIP_RE.sub("", (text or "")).lower()


def is_affirmative(text: str | None) -> bool:
    return _normalize(text) in _AFFIRMATIVE


def is_cancel(text: str | None) -> bool:
    return _normalize(text) in _CANCEL
