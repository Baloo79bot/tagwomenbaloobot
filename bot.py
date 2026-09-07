import logging, os, asyncio, html, psycopg2
from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get("TOKEN", "IL_TUO_TOKEN_TELEGRAM")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS female_users (
            user_id BIGINT, chat_id BIGINT, first_name TEXT,
            PRIMARY KEY (user_id, chat_id)
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()

async def handle_ping(request):
    return web.Response(text="Bot is running OK!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/ping', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type == "private":
        await update.message.reply_text("Questo comando funziona solo nei gruppi.")
        return False
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in ['administrator', 'creator']:
        await update.message.reply_text("Funzione riservata ai soli admin.")
        return False
    return True

async def add_f(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Devi usare questo comando *in risposta* al messaggio dell'utente.", parse_mode=ParseMode.MARKDOWN)
        return
    
    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    if target_user.is_bot:
        await update.message.reply_text("Non puoi aggiungere un bot alla lista.")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO female_users (user_id, chat_id, first_name) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET first_name = EXCLUDED.first_name;
        """, (target_user.id, chat_id, target_user.first_name or "Utente"))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text(f"✅ {html.escape(target_user.first_name or 'Utente')} aggiunta!", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore add_f: {e}")
        await update.message.reply_text(f"⚠️ Errore salvataggio DB: {e}")

async def del_f(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Devi usare questo comando *in risposta* all'utente da rimuovere.", parse_mode=ParseMode.MARKDOWN)
        return
    
    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM female_users WHERE user_id = %s AND chat_id = %s;", (target_user.id, chat_id))
        count = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        if count > 0:
            await update.message.reply_text(f"🗑 {html.escape(target_user.first_name or 'Utente')} rimossa.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("L'utente non era presente nel database.")
    except Exception as e:
        logging.error(f"Errore del_f: {e}")
        await update.message.reply_text(f"⚠️ Errore rimozione DB: {e}")

async def list_females(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    chat_id = update.effective_chat.id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name FROM female_users WHERE chat_id = %s;", (chat_id,))
        users = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Errore lettura DB in list_females: {e}")
        await update.message.reply_text(f"⚠️ Errore di connessione al DB: {e}")
        return

    if not users:
        await update.message.reply_text("Nessuna utente salvata in questo gruppo.")
        return

    mentions = []
    for u_id, name in users:
        safe_name = html.escape(name) if name else "Utente"
        mentions.append(f'<a href="tg://user?id={u_id}">{safe_name}</a>')

    text = "📋 **Lista utenti salvate nel database:**\n" + ", ".join(mentions)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def tagf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    chat_id = update.effective_chat.id
    
    reply_to_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name FROM female_users WHERE chat_id = %s;", (chat_id,))
        users = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Errore lettura DB in tagf: {e}")
        await update.message.reply_text(f"⚠️ Errore di connessione al DB: {e}")
        return

    if not users:
        await update.message.reply_text("Nessuna utente salvata in questo gruppo.")
        return

    try:
        await update.message.delete()
    except Exception as e:
        logging.warning(f"Impossibile eliminare messaggio comando: {e}")

    mentions = []
    for u_id, name in users:
        safe_name = html.escape(name) if name else "Utente"
        mentions.append(f'<a href="tg://user?id={u_id}">{safe_name}</a>')

    chunk_size = 5
    for i in range(0, len(mentions), chunk_size):
        chunk = mentions[i:i + chunk_size]
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=", ".join(chunk),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to_id
            )
        except Exception as e:
            logging.error(f"Errore invio messaggio tag: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Errore invio tag: {e}")
        
        if i + chunk_size < len(mentions):
            await asyncio.sleep(3)

async def post_init(application: Application):
    asyncio.create_task(start_web_server())

def main():
    if not DATABASE_URL: raise ValueError("DATABASE_URL non impostata!")
    init_db()
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("add_f", add_f))
    application.add_handler(CommandHandler("del_f", del_f))
    application.add_handler(CommandHandler("femminucce", list_females))
    application.add_handler(CommandHandler("tagf", tagf))
    print("Bot avviato...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
