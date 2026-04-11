import logging

logger = logging.getLogger(__name__)

def build_assessment_prompt() -> str:
    """構建模型自評（Complexity Assessment）提示詞。"""
    return """
## Task Complexity Assessment
作為 Omni-Agent 的中腦（Planner），在回應使用者之前，請先評估該請求的複雜度。

請判斷目前的對話情境與使用者需求，並輸出評估結果。
複雜度定義：
- low: 簡單問候、短句回應、翻譯、簡單事實查詢。
- medium: 需要邏輯推理、多步思考、或是呼叫現有技能（Skills）。
- high: 複雜的情境分析、代碼編寫、長文本總結、或是涉及高度風險的系統操作。

你的輸出必須包含一個 JSON 區塊（若同時需要執行技能，請合併在同一個 JSON 中）：
```json
{
  "complexity": "low" | "medium" | "high",
  "reasoning": "簡短的評估理由"
}
```
注意：請僅做評估，系統會自動決定是否根據此評估結果升級模型。
"""

def build_system_prompt(soul_content: str, memories: list[str] = None) -> str:
    """構建完整的系統提示詞（System Prompt）。"""
    prompt = soul_content
    
    if memories:
        prompt += "\n\n## Long-term Memory\n以下是與該使用者過去對話的相關記憶摘要：\n"
        for m in memories:
            prompt += f"- {m}\n"
            
    prompt += "\n\n" + build_assessment_prompt()
    
    return prompt
