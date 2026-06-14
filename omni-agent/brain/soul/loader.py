import logging
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
import asyncpg

logger = logging.getLogger("brain.soul.loader")

class SoulNotFoundError(Exception):
    """Thrown when SOUL.md is not found."""
    pass

class SoulLoader:
    def __init__(self, soul_path: str, template_dir: str, pool: asyncpg.Pool):
        self.soul_path = soul_path
        self.pool = pool
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape()
        )
        self._static_soul = None
        self._last_mtime = 0

    def _load_static_soul(self) -> str:
        if not os.path.exists(self.soul_path):
            raise SoulNotFoundError(f"SOUL.md not found at {self.soul_path}")

        mtime = os.path.getmtime(self.soul_path)
        if self._static_soul is None or mtime > self._last_mtime:
            with open(self.soul_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Split at Dynamic Injection Zone if it exists
                if "## Dynamic Injection Zone" in content:
                    self._static_soul = content.split("## Dynamic Injection Zone")[0].strip()
                else:
                    self._static_soul = content.strip()
            self._last_mtime = mtime
        return self._static_soul

    async def render(self, user_id: str) -> str:
        try:
            static_content = self._load_static_soul()
        except SoulNotFoundError as e:
            logger.error(f"SoulLoader error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load SOUL.md: {e}")
            return "I am Cindy, a family AI assistant."

        dynamic_context = {}

        # 權威「現在」：給模型時間錨點（修日期幻覺）。容器 TZ=Asia/Taipei，naive
        # datetime.now() 即台北時間。放動態區（非快取段），不影響 SOUL prefix 命中。
        _n = datetime.now()
        _wd = "一二三四五六日"[_n.weekday()]
        dynamic_context["now"] = f"{_n.strftime('%Y-%m-%d')}（週{_wd}）{_n.strftime('%H:%M')}（台北）"

        try:
            # Fetch stress logs
            async with self.pool.acquire() as conn:
                stress_logs = await conn.fetch(
                    "SELECT level, action_taken, mood, created_at FROM stress_logs ORDER BY created_at DESC LIMIT 3"
                )
                # created_at 為 timestamptz（asyncpg 回 UTC-aware）→ 轉容器本地(台北)再顯示
                sl = [dict(log) for log in stress_logs]
                for s in sl:
                    if s.get("created_at") is not None:
                        s["created_at"] = s["created_at"].astimezone()
                dynamic_context["recent_stress_logs"] = sl

                # Fetch home_context (Family Pulse + Today Context + Memory Index)
                rows = await conn.fetch(
                    "SELECT key, value FROM home_context WHERE key IN ('home_events', 'today_context', $1)",
                    f"memory_index:{user_id}"
                )
                for row in rows:
                    if row['key'] == 'home_events':
                        dynamic_context["home_events"] = row['value']
                    elif row['key'] == 'today_context':
                        dynamic_context["today_context"] = row['value']
                    elif row['key'] == f"memory_index:{user_id}":
                        dynamic_context["memory_index"] = row['value']

        except Exception as e:
            # DB 失敗不致命：仍渲染 now（時間錨點）與已取得的內容，不退回純靜態。
            logger.error(f"Database error in SoulLoader: {e}. Rendering with partial context.")

        try:
            template = self.jinja_env.get_template("context.md.jinja")
            dynamic_section = template.render(**dynamic_context)

            full_prompt = static_content
            if dynamic_section.strip():
                full_prompt += "\n\n---\n\n" + dynamic_section.strip()

            return full_prompt
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return static_content
