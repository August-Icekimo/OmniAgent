import logging
import os
import base64
from typing import Optional
import pypdf
import pandas as pd
import anthropic
from llm import Message, Role, ModelRouter

logger = logging.getLogger("brain.skills.file_analyzer")

class FileAnalyzer:
    """提供 PDF、圖片、Excel 的分析功能。"""

    def __init__(self, router: ModelRouter, db_pool=None):
        self.router = router
        self.db_pool = db_pool

    async def analyze(self, local_path: str, mime_type: str, instruction: Optional[str] = None) -> str:
        """依 MIME type 路由至對應 handler 進行分析。"""
        logger.info(f"Analyzing file: {local_path} ({mime_type})")
        
        # 1. 驗證路徑安全性 (NF-02)
        if not local_path.startswith("/workspace/uploads/"):
            logger.warning(f"Path traversal attempt: {local_path}")
            return "錯誤：無權存取此路徑。"

        if not os.path.exists(local_path):
            logger.warning(f"File not found: {local_path}")
            return "檔案已不存在，可能已超過保存期限。"

        # 2. 更新最後存取時間 (F-03)
        if self.db_pool:
            try:
                await self.db_pool.execute(
                    "UPDATE file_workspace_log SET last_accessed_at = NOW() WHERE local_path = $1",
                    local_path
                )
            except Exception as e:
                logger.warning(f"Failed to touch file log: {e}")

        # 3. 執行分析
        try:
            if mime_type == "application/pdf":
                return await self._analyze_pdf(local_path, instruction)
            elif mime_type.startswith("image/"):
                return await self._analyze_image(local_path, mime_type, instruction)
            elif mime_type in [
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
                "text/csv"
            ]:
                return await self._analyze_excel(local_path, instruction)
            else:
                return f"不支援此檔案格式（{mime_type}）"
        except Exception as e:
            logger.error(f"Analysis failed for {local_path}: {e}")
            return f"檔案分析失敗：{str(e)}"

    async def _analyze_pdf(self, path: str, instruction: Optional[str]) -> str:
        """萃取 PDF 純文字並摘要。"""
        try:
            text = ""
            with open(path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            
            if not text.strip():
                return "PDF 內容為空或無法讀取（可能是掃描件，目前尚不支援 OCR PDF）。"

            prompt = f"請分析以下 PDF 內容，並根據指示進行摘要或回答。\n指示：{instruction or '請總結這份文件的重點'}\n\n內容：\n{text[:10000]}" # 限制長度
            
            response = await self.router.chat(
                [Message(role=Role.USER, content=prompt)],
                provider="gemini" # 預設用 Gemini Flash 摘要文字
            )
            return response.content
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return "PDF 無法讀取，可能已加密或損壞。"

    async def _analyze_image(self, path: str, mime_type: str, instruction: Optional[str]) -> str:
        """使用 Claude Vision 進行圖片分析。"""
        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # 由於目前 Router 尚未整合多模態，此處暫時直連 Claude
            # 未來應擴充 Router 支援
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return "系統尚未配置 ANTHROPIC_API_KEY，無法分析圖片。"

            client = anthropic.AsyncAnthropic(api_key=api_key)
            message = await client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": instruction or "請描述這張圖片的內容，如果包含文字，請進行 OCR 萃取。"
                            }
                        ],
                    }
                ],
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Image analysis error: {e}")
            return f"圖片分析失敗：{str(e)}"

    async def _analyze_excel(self, path: str, instruction: Optional[str]) -> str:
        """讀取 Excel/CSV 並摘要結構。"""
        try:
            if path.endswith(".csv"):
                df = pd.read_csv(path)
                data_str = df.head(50).to_string() # 僅取前 50 筆
            else:
                # 讀取 Excel
                xl = pd.ExcelFile(path)
                sheets_data = []
                for sheet_name in xl.sheet_names[:5]: # 最多 5 個 sheet
                    df = pd.read_excel(path, sheet_name=sheet_name)
                    sheets_data.append(f"Sheet: {sheet_name}\n{df.head(20).to_string()}")
                data_str = "\n\n".join(sheets_data)

            prompt = f"請分析以下表格資料，並根據指示進行解讀。\n指示：{instruction or '請總結這些資料的內容與趨勢'}\n\n資料摘要：\n{data_str}"
            
            response = await self.router.chat(
                [Message(role=Role.USER, content=prompt)],
                provider="gemini"
            )
            return response.content
        except Exception as e:
            logger.error(f"Excel analysis error: {e}")
            return f"表格讀取失敗：{str(e)}"
