import logging
import os
import base64
import uuid
from typing import Optional
import pypdf
import pandas as pd
import json
from llm import Message, Role, ModelRouter
from .tgs_converter import tgs_to_png

logger = logging.getLogger("brain.skills.file_analyzer")

class FileAnalyzer:
    """提供 PDF、圖片、Excel 的分析功能。"""

    def __init__(self, router: ModelRouter, db_pool=None):
        self.router = router
        self.db_pool = db_pool

    async def analyze(self, local_path: str, mime_type: str, instruction: Optional[str] = None, media_type: Optional[str] = None, user_id: Optional[str] = None, platform: Optional[str] = None, source_message_id: Optional[str] = None) -> str:
        """依 MIME type 或 Media type 路由至對應 handler 進行分析。"""
        logger.info(f"Analyzing file: {local_path} ({mime_type}, media_type={media_type})")
        
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
            if media_type == "voice":
                return await self._analyze_voice(local_path, mime_type, instruction, user_id, platform, source_message_id)
            elif media_type == "video":
                return await self._analyze_video(local_path, mime_type, instruction)
            elif media_type == "sticker" or media_type == "tgs_sticker":
                return await self._analyze_sticker(local_path, mime_type, instruction, media_type)
            elif media_type == "animation":
                return await self._analyze_animation(local_path, mime_type, instruction)
            elif mime_type == "application/pdf":
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
        """使用 Gemini Flash 進行圖片分析 (Phase 4D 兩階段視覺流)。"""
        try:
            with open(path, "rb") as f:
                image_bytes = f.read()
                image_data = base64.b64encode(image_bytes).decode("utf-8")

            # Stage 1: OCR Fast Path
            ocr_prompt = "請僅萃取圖片中的所有文字。如果沒有文字，請回傳 [EMPTY]。"
            ocr_content = [
                {"type": "image", "mime_type": mime_type, "data": image_data},
                {"type": "text", "text": ocr_prompt}
            ]
            ocr_response = await self.router.chat([Message(role=Role.USER, content=ocr_content)], provider="gemini")
            ocr_text = ocr_response.content.strip()

            # 判斷是否需要 Stage 2
            if ocr_text != "[EMPTY]" and ocr_text != "":
                # 簡單評估 OCR 是否足以回答指令
                eval_prompt = f"用戶指令：{instruction or '無'}\nOCR 萃取文字：\n{ocr_text}\n\n請問僅憑這些文字是否足以精確回答用戶指令？請回傳 YES 或 NO。"
                eval_response = await self.router.chat([Message(role=Role.USER, content=eval_prompt)], provider="gemini")
                if "YES" in eval_response.content.upper():
                    logger.info("Stage 1 OCR sufficient, skipping Stage 2.")
                    return f"[OCR 萃取結果]\n{ocr_text}"

            # Stage 2: Multimodal Escalation
            logger.info("Escalating to Stage 2 vision.")
            vision_prompt = instruction or "請詳細描述這張圖片的內容，並回答相關問題。"
            vision_content = [
                {"type": "image", "mime_type": mime_type, "data": image_data},
                {"type": "text", "text": vision_prompt}
            ]
            vision_response = await self.router.chat([Message(role=Role.USER, content=vision_content)], provider="gemini")
            return vision_response.content
        except Exception as e:
            logger.error(f"Image analysis error: {e}")
            return f"圖片分析失敗：{str(e)}"

    async def _analyze_voice(self, path: str, mime_type: str, instruction: Optional[str], user_id: str, platform: str, source_msg_id: str) -> str:
        """語音訊息處理：轉錄、儲存並產生回應。"""
        try:
            with open(path, "rb") as f:
                audio_bytes = f.read()
                audio_data = base64.b64encode(audio_bytes).decode("utf-8")

            # 請求 Gemini 進行轉錄與回應
            prompt = "這是一段語音訊息。請先提供逐字稿（Transcript），然後根據內容進行回應。請務必遵守以下格式：\nTranscript: [逐字稿內容]\nReply: [回應內容]"
            content = [
                {"type": "audio", "mime_type": mime_type, "data": audio_data},
                {"type": "text", "text": prompt}
            ]

            response = await self.router.chat([Message(role=Role.USER, content=content)], provider="gemini")
            full_text = response.content

            # 解析轉錄內容與回應
            transcript = "[no_speech_detected]"
            reply = full_text
            if "Transcript:" in full_text and "Reply:" in full_text:
                parts = full_text.split("Reply:", 1)
                reply = parts[1].strip()
                transcript = parts[0].replace("Transcript:", "").strip()

            # 儲存至 DB (Phase 4D)
            if self.db_pool and user_id:
                try:
                    # 獲取 duration (可能需要從 metadata 傳入，這裡先暫留)
                    await self.db_pool.execute(
                        """
                        INSERT INTO voice_transcripts (user_id, source_platform, source_message_id, transcript, audio_path)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        uuid.UUID(user_id), platform, source_msg_id or "unknown", transcript, path
                    )
                except Exception as e:
                    logger.error(f"Failed to store voice transcript: {e}")

            return reply
        except Exception as e:
            logger.error(f"Voice analysis error: {e}")
            return f"語音處理失敗：{str(e)}"

    async def _analyze_sticker(self, path: str, mime_type: str, instruction: Optional[str], media_type: str) -> str:
        """貼圖語義分析。"""
        if media_type == "tgs_sticker":
            png_path = path + ".png"
            if tgs_to_png(path, png_path):
                path = png_path
                mime_type = "image/png"
            else:
                return "[sticker: 動態 Lottie 貼圖, 無法解析內容]"

        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # 清理暫存檔 (如果是我們產生的 PNG)
            if media_type == "tgs_sticker" and path.endswith(".png") and os.path.exists(path):
                # 我們稍後再刪除，先讀取完
                pass

            prompt = "這是貼圖，請描述其情緒、物體或意圖。請以簡短的一句話回傳，格式如：[sticker: 某某動作，表達某某心情]。"
            content = [
                {"type": "image", "mime_type": mime_type, "data": image_data},
                {"type": "text", "text": prompt}
            ]

            response = await self.router.chat([Message(role=Role.USER, content=content)])
            
            # 清理 TGS 轉換產生的暫存 PNG
            if media_type == "tgs_sticker" and path.endswith(".png") and os.path.exists(path):
                os.remove(path)

            return response.content
        except Exception as e:
            logger.error(f"Sticker analysis error: {e}")
            return "[sticker]"

    async def _analyze_video(self, path: str, mime_type: str, instruction: Optional[str]) -> str:
        """使用 Gemini Native Video 分析影片內容。"""
        try:
            with open(path, "rb") as f:
                video_data = base64.b64encode(f.read()).decode("utf-8")

            prompt = f"請分析這段影片，並根據指示進行回答。\n指示：{instruction or '請描述影片發生的事情與主要人物/物體'}"
            content = [
                {"type": "video", "mime_type": mime_type, "data": video_data},
                {"type": "text", "text": prompt}
            ]

            response = await self.router.chat([Message(role=Role.USER, content=content)])
            return response.content
        except Exception as e:
            logger.error(f"Video analysis error: {e}")
            return f"影片分析失敗：{str(e)}"

    async def _analyze_animation(self, path: str, mime_type: str, instruction: Optional[str]) -> str:
        """GIF/動畫首幀分析。"""
        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            prompt = "這是 GIF 動畫的首幀，全貌可能不同。請描述此幀的內容並推測動畫意圖。"
            content = [
                {"type": "image", "mime_type": mime_type, "data": image_data},
                {"type": "text", "text": prompt}
            ]

            response = await self.router.chat([Message(role=Role.USER, content=content)])
            return response.content
        except Exception as e:
            logger.error(f"Animation analysis error: {e}")
            return f"動畫分析失敗：{str(e)}"

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
                [Message(role=Role.USER, content=prompt)]
            )
            return response.content
        except Exception as e:
            logger.error(f"Excel analysis error: {e}")
            return f"表格讀取失敗：{str(e)}"
