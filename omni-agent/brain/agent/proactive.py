import asyncio
import logging
import os
from datetime import datetime
import httpx

logger = logging.getLogger("brain.proactive")

async def start_proactive_tasks(app):
    """啟動所有主動推送相關的背景任務。"""
    asyncio.create_task(stranger_summary_task(app))
    asyncio.create_task(workspace_cleanup_task(app))

async def stranger_summary_task(app):
    """每日 21:00 (預設) 推送陌生人訪問摘要給 Admin。"""
    while True:
        try:
            # 獲取設定的時間
            report_time = "21:00"
            if app.state.db_pool:
                row = await app.state.db_pool.fetchrow(
                    "SELECT value FROM home_context WHERE key = 'setting:stranger_report_time'"
                )
                if row:
                    report_time = row['value'].get('time', "21:00")
            
            now = datetime.now()
            target_time = datetime.strptime(report_time, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            
            if now > target_time:
                # 已經過了今天的時間，等明天
                await asyncio.sleep(60 * 60) # 每小時檢查一次
                continue
            
            # 距離目標時間還有多久
            wait_seconds = (target_time - now).total_seconds()
            if wait_seconds > 60:
                await asyncio.sleep(min(wait_seconds, 3600))
                continue
            
            # 時間到了！執行摘要（陌生人 + 投遞失敗 dead-letter）
            logger.info("Running daily admin summaries...")
            await send_stranger_summary(app)
            await send_undeliverable_summary(app)

            # 執行完後等一小時避免重複觸發
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"Stranger summary task error: {e}")
            await asyncio.sleep(60)

async def send_stranger_summary(app):
    """從 DB 抓取未通知的陌生人記錄並發送。"""
    if not app.state.db_pool:
        return
        
    rows = await app.state.db_pool.fetch(
        "SELECT id, platform, external_id, first_message FROM stranger_knocks WHERE notified_at IS NULL"
    )
    if not rows:
        return
    
    # 格式化訊息
    summary = "📢 **今日陌生人訪問摘要**\n\n"
    ids_to_update = []
    for r in rows:
        summary += f"- [{r['platform']}] {r['external_id']}: {r['first_message'][:50]}\n"
        ids_to_update.append(r['id'])
    
    # 發送給所有 Admin
    admin_chats = await app.state.db_pool.fetch(
        "SELECT chat_id FROM telegram_accounts ta JOIN users u ON ta.user_id = u.id WHERE u.role = 'admin'"
    )
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or not admin_chats:
        logger.warning("TELEGRAM_BOT_TOKEN not set or no admin found, summary skipped")
        return

    async with httpx.AsyncClient() as client:
        for admin in admin_chats:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": admin['chat_id'], "text": summary, "parse_mode": "Markdown"}
            )
            
    # 更新 notified_at
    await app.state.db_pool.execute(
        "UPDATE stranger_knocks SET notified_at = NOW() WHERE id = ANY($1)",
        ids_to_update
    )

async def _send_to_admins(app, text: str) -> bool:
    """把一段文字推播給所有 admin（Telegram）。回傳是否確實送出。"""
    admin_chats = await app.state.db_pool.fetch(
        "SELECT chat_id FROM telegram_accounts ta JOIN users u ON ta.user_id = u.id WHERE u.role = 'admin'"
    )
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or not admin_chats:
        logger.warning("TELEGRAM_BOT_TOKEN not set or no admin found, admin push skipped")
        return False
    async with httpx.AsyncClient() as client:
        for admin in admin_chats:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": admin['chat_id'], "text": text, "parse_mode": "Markdown"}
            )
    return True

async def send_undeliverable_summary(app):
    """彙報新出現的 undeliverable turn（投遞耗盡的 dead-letter）給 admin。
    以 home_context 水位（reported_until）去重，避免重複彙報；沒送出就不推進水位。"""
    pool = app.state.db_pool
    if not pool:
        return

    # 去重水位：上次已彙報到的 updated_at 時間點。
    wm_row = await pool.fetchrow(
        "SELECT value FROM home_context WHERE key = 'undeliverable:reported_until'"
    )
    watermark = wm_row['value'].get('ts') if wm_row else None

    rows = await pool.fetch(
        """
        SELECT id::text AS id, user_id::text AS user_id, platform,
               updated_at, COALESCE(result, '') AS result
        FROM turns
        WHERE status = 'undeliverable'
          AND ($1::timestamptz IS NULL OR updated_at > $1::timestamptz)
        ORDER BY updated_at ASC
        """,
        watermark,
    )
    if not rows:
        return  # 無新項：不推空摘要

    summary = "🚨 **投遞失敗（undeliverable）摘要**\n\n"
    for r in rows:
        snippet = r['result'][:50].replace("\n", " ")
        summary += (
            f"- [{r['platform']}] turn `{r['id'][:8]}` user {r['user_id'][:8]} "
            f"@ {r['updated_at']:%m-%d %H:%M}：{snippet}\n"
        )

    if not await _send_to_admins(app, summary):
        return  # 沒送出就不推進水位，下次再試

    # 推進水位到本批最新（rows 已按 updated_at ASC）。
    newest = rows[-1]['updated_at'].isoformat()
    await pool.execute(
        """
        INSERT INTO home_context (key, value)
        VALUES ('undeliverable:reported_until', jsonb_build_object('ts', $1::text))
        ON CONFLICT (key) DO UPDATE SET value = jsonb_build_object('ts', $1::text)
        """,
        newest,
    )

async def workspace_cleanup_task(app):
    """每小時清理超過 120 小時未存取的檔案。"""
    logger.info("Workspace cleanup task started")
    while True:
        try:
            if not app.state.db_pool:
                await asyncio.sleep(60)
                continue
                
            # 1. 找出超過 120 小時未存取的記錄
            rows = await app.state.db_pool.fetch(
                "SELECT local_path FROM file_workspace_log WHERE last_accessed_at < NOW() - INTERVAL '120 hours'"
            )
            
            if rows:
                count = 0
                for r in rows:
                    path = r['local_path']
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            count += 1
                        # 無論檔案是否存在，都從 DB 移除記錄
                        await app.state.db_pool.execute(
                            "DELETE FROM file_workspace_log WHERE local_path = $1",
                            path
                        )
                    except Exception as e:
                        logger.error(f"Failed to delete {path}: {e}")
                
                if count > 0:
                    logger.info(f"Cleaned up {count} expired files from workspace")
            
            await asyncio.sleep(3600) # 每小時執行一次
            
        except Exception as e:
            logger.error(f"Workspace cleanup task error: {e}")
            await asyncio.sleep(60)
