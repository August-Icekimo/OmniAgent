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
