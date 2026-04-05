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
        try:
            # Fetch stress logs
            async with self.pool.acquire() as conn:
                stress_logs = await conn.fetch(
                    "SELECT level, action_taken, mood, created_at FROM stress_logs ORDER BY created_at DESC LIMIT 3"
                )
                dynamic_context["recent_stress_logs"] = [dict(log) for log in stress_logs]

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
            logger.error(f"Database error in SoulLoader: {e}. Falling back to static content.")
            return static_content

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
