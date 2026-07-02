"""AGY 長文摘要 specialist agent（google-adk 2.x）。

純 LLM 摘要器，外加一個 read_workspace_file 工具，讓 brain 可用「共享工作區檔名」
而非 inline 長文作為輸入（提案 D2 產物交換）。模型走 Gemini API Key（容器注入的
單一 secret），與 Cindy 日常 OAuth 計費分離（D3）。
"""

import os

from google.adk import Agent
from google.adk.tools.tool_context import ToolContext

A2A_WORKSPACE = os.getenv("A2A_WORKSPACE", "/a2a-workspace")
SUMMARIZER_MODEL = os.getenv("AGY_MODEL", "gemini-2.5-flash")


def read_workspace_file(filename: str, tool_context: ToolContext) -> str:
    """讀取共享工作區內一個 UTF-8 純文字檔的內容。

    當摘要輸入是以「檔名」提供（而非 inline 正文）時使用本工具。

    Args:
      filename: 共享工作區內的純檔名（不含目錄；會自動去除路徑以防穿越）。
      tool_context: ADK 注入的工具上下文。

    Returns:
      檔案文字內容；找不到或讀取失敗時回傳以 [read_workspace_file error: ...] 包裹的訊息。
    """
    safe = os.path.basename(filename)  # 防路徑穿越：只取檔名
    path = os.path.join(A2A_WORKSPACE, safe)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001 — 讀檔錯誤回傳給模型，不中斷 agent
        return f"[read_workspace_file error: {e}]"


root_agent = Agent(
    name="summarizer",
    model=SUMMARIZER_MODEL,
    description="長文摘要 specialist：把長文濃縮成精簡、忠實原意的重點摘要。",
    instruction=(
        "你是長文摘要專家。把使用者提供的長文濃縮成精簡、忠實原意的摘要。\n"
        "- 預設以繁體中文輸出（除非原文明確要求其他語言）。\n"
        "- 保留關鍵事實、結論與行動項；剔除冗詞與重複。\n"
        "- 若輸入看起來是一個檔名（如 .txt/.md 結尾且沒有正文），"
        "用 read_workspace_file 工具讀取共享工作區的檔案內容後再摘要。\n"
        "- 只輸出摘要本身，不要前言、寒暄或結語。"
    ),
    tools=[read_workspace_file],
)
