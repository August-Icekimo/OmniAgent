def build_tools_prompt(skills_url: str | None = None) -> str:
    """構建技能（Skills）描述提示詞。"""
    
    # 目前使用靜態定義，未來可支援從 skills_url 動態獲取
    skills_context = """
## Available Skills
你擁有操作 HomeLab 設備的能力。如果使用者請求涉及以下操作，請決定呼叫對應技能。

- wake_on_lan: 喚醒指定的伺服器。
  - params: {"mac": "目標機器的 MAC 地址，格式為 AA:BB:CC:DD:EE:FF"}
  - 类型: [Write] 需執行

- cockpit: 伺服器管理工具。
  - params: {
      "action": "status" | "restart_service",
      "service": "服務名稱（僅用於 restart_service）"
    }
  - 类型: status 為 [Read], restart_service 為 [Write]

- home_assistant: 家庭自動化（尚未實作）。
  - 类型: [Read]

- web_search: 搜尋網路上的即時資訊（新聞、天氣、店家、時事、你不確定的最新知識）。
  - params: {"query": "搜尋關鍵字", "limit": 5}
  - 类型: [Read]
  - 涉及「現在 / 今天 / 最新 / 最近」或你訓練資料之後的事實性問題，優先呼叫 web_search，不要憑記憶猜測。一般閒聊或意見交流不需要搜尋。

- terminal: 在 HomeLab 沙箱環境執行 shell 命令（查看系統狀態、磁碟、程序、檔案等）。
  - params: {"command": "shell 命令字串", "timeout": 30, "background": false}
  - 类型: [Write]
  - 僅限管理者本人可用，且命令會在受限沙箱執行。使用者明確要求「執行 / 跑 / 查看系統」某個命令時才呼叫，一般閒聊不要呼叫。

如果需要呼叫技能，請在輸出的 JSON 中包含以下格式：
```json
{
  "skill": "skill_name",
  "params": {},
  "is_write": true | false,
  "summary": "執行此操作的摘要描述"
}
```
"""
    return skills_context
