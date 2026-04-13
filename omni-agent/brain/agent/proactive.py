import asyncio
import logging
import os
import json
from datetime import datetime
import httpx

logger = logging.getLogger("brain.proactive")

async def start_proactive_tasks(app):
    """啟動所有主動推送相關的背景任務。"""
    asyncio.create_task(stranger_summary_task(app))
    asyncio.create_task(stress_escalation_task(app))

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
            
            # 時間到了！執行摘要
            logger.info("Running stranger summary task...")
            await send_stranger_summary(app)
            
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

async def stress_escalation_task(app):
    """監控壓力日誌，必要時發起升級提案。"""
    while True:
        try:
            if not app.state.db_pool:
                await asyncio.sleep(60)
                continue
                
            # 檢查最新壓力狀態
            row = await app.state.db_pool.fetchrow(
                "SELECT level FROM stress_logs ORDER BY created_at DESC LIMIT 1"
            )
            
            if row and row['level'] in ['StressOverload', 'StressCritical']:
                # 檢查是否有 pending 的提案
                pending = await app.state.db_pool.fetchrow(
                    "SELECT value FROM home_context WHERE key = 'escalation:pending'"
                )
                
                if not pending:
                    # 發起新提案
                    await initiate_escalation(app, row['level'])
                else:
                    # 檢查超時 (1 小時)
                    start_time = datetime.fromisoformat(pending['value']['start_time'])
                    if (datetime.now() - start_time).total_seconds() > 3600:
                        logger.info("Escalation timed out, clearing status")
                        await app.state.db_pool.execute(
                            "DELETE FROM home_context WHERE key = 'escalation:pending'"
                        )
            
            await asyncio.sleep(300) # 每 5 分鐘檢查一次
            
        except Exception as e:
            logger.error(f"Stress escalation task error: {e}")
            await asyncio.sleep(60)

async def initiate_escalation(app, stress_level):
    """向 Admin 發送升級提案。"""
    logger.info(f"Initiating escalation for stress level: {stress_level}")
    
    upgrade_model = os.getenv("BRAIN_UPGRADE_MODEL", "claude-opus-4-6")
    msg = f"🎛️ **系統警報：壓力指數 {stress_level}**\n\n目前服務負載較高，建議暫時將大腦模型升級至 `{upgrade_model}` 以確保回覆品質與穩定性。請問要現在執行升級嗎？"
    
    # 存入 pending 狀態
    await app.state.db_pool.execute(
        "INSERT INTO home_context (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        "escalation:pending",
        json.dumps({
            "start_time": datetime.now().isoformat(),
            "target_model": upgrade_model,
            "status": "waiting"
        })
    )
    
    # 發送給 Admin
    admin_chats = await app.state.db_pool.fetch(
        "SELECT chat_id FROM telegram_accounts ta JOIN users u ON ta.user_id = u.id WHERE u.role = 'admin'"
    )
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        async with httpx.AsyncClient() as client:
            for admin in admin_chats:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": admin['chat_id'], "text": msg, "parse_mode": "Markdown"}
                )
