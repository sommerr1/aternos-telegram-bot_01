import os
import asyncio
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("TG_TOKEN")
ALLOWED_USER_ID = int(os.getenv("USER_ID", 0))

KEY_FILE = "session_key.txt"
VAL_FILE = "session_val.txt"

DEFAULT_KEY = "aps:ваша_сессия:sessionMarker"
DEFAULT_VAL = "ваш_длинный_токен_значение"

# --- ХИТРОСТЬ ДЛЯ ОБХОДА ОШИБКИ PORT TIMEOUT НА RENDER ---
class FakeWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_fake_web_server():
    # Render автоматически передает номер порта в переменную PORT
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), FakeWebHandler)
    server.serve_forever()
# --------------------------------------------------------

def init_session_files():
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(DEFAULT_KEY)
    if not os.path.exists(VAL_FILE):
        with open(VAL_FILE, "w", encoding="utf-8") as f: f.write(DEFAULT_VAL)

def get_current_session():
    init_session_files()
    with open(KEY_FILE, "r", encoding="utf-8") as f: s_key = f.read().strip()
    with open(VAL_FILE, "r", encoding="utf-8") as f: s_val = f.read().strip()
    return s_key, s_val

bot = Bot(token=TOKEN)
dp = Dispatcher()

def is_owner(message: types.Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запустить", callback_data="srv_start")
    builder.button(text="⏹️ Остановить", callback_data="srv_stop")
    builder.button(text="📊 Статус", callback_data="srv_status")
    builder.button(text="💻 Консоль", callback_data="srv_console")
    builder.adjust(2)
    return builder.as_markup()

def aternos_action(action_type):
    try:
        storage_key, storage_val = get_current_session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Authorization": f"Bearer {storage_val}",
            "Cookie": f"{storage_key}={storage_val}"
        }
        
        if action_type == "status":
            res = requests.get("https://aternos.org", headers=headers, timeout=10)
            if "online" in res.text: return "🟢 Онлайн"
            if "starting" in res.text or "loading" in res.text: return "⏳ Запускается..."
            if "stopping" in res.text: return "🛑 Выключается..."
            return "🔴 Выключен"
            
        elif action_type == "start":
            page = requests.get("https://aternos.org", headers=headers, timeout=10)
            if 'AJAX_TOKEN' in page.text:
                ajax_token = page.text.split('AJAX_TOKEN = "')[1].split('"')[0]
                res = requests.post(f"https://aternos.org{ajax_token}", headers=headers, timeout=10)
                return "🚀 Запрос на запуск отправлен!" if res.status_code == 200 else "⚠️ Ошибка запуска."
            return "⚠️ Не удалось верифицировать сессию."
            
        elif action_type == "stop":
            page = requests.get("https://aternos.org", headers=headers, timeout=10)
            if 'AJAX_TOKEN' in page.text:
                ajax_token = page.text.split('AJAX_TOKEN = "')[1].split('"')[0]
                res = requests.post(f"https://aternos.org{ajax_token}", headers=headers, timeout=10)
                return "🛑 Сигнал на остановку отправлен." if res.status_code == 200 else "⚠️ Ошибка остановки."
            return "⚠️ Не удалось верифицировать сессию."
            
        elif action_type == "console":
            res = requests.get("https://aternos.org", headers=headers, timeout=10)
            lines = res.text.split("\n")[-15:]
            return "\n".join(lines) if res.text else "Консоль пуста."
            
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if not is_owner(message): return
    await message.answer("👋 Бот успешно запущен на бесплатном Web Service! Выберите действие:", reply_markup=get_main_keyboard())

@dp.message(Command("update_session"))
async def update_session_cmd(message: types.Message):
    if not is_owner(message): return
    try:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("⚠️ Неверный формат! Отправьте команду так:\n`/update_session ИМЯ_КЛЮЧА ЗНАЧЕНИЕ_VALUE`", parse_mode="Markdown")
            return
        
        with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(args[1])
        with open(VAL_FILE, "w", encoding="utf-8") as f: f.write(args[2])
        await message.answer("✅ Сессионные маркеры успешно обновлены!")
    except Exception as e:
        await message.answer(f"❌ Ошибка обновления: {str(e)}")

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != ALLOWED_USER_ID: return
    action = callback.data
    await callback.answer("Выполняю запрос...")
    if action == "srv_start": await callback.message.answer(aternos_action("start"))
    elif action == "srv_stop": await callback.message.answer(aternos_action("stop"))
    elif action == "srv_status":
        status = aternos_action("status")
        await callback.message.answer(f"📊 *Состояние сервера:*\n• Статус: {status}", parse_mode="Markdown")
    elif action == "srv_console":
        console = aternos_action("console")
        await callback.message.answer(f"💻 *Последние строки консоли:*\n```\n{console}\n```", parse_mode="Markdown")

async def main():
    init_session_files()
    # Запускаем фейковый веб-сервер в отдельном потоке, чтобы Render его «увидел»
    Thread(target=run_fake_web_server, daemon=True).start()
    # Запускаем самого бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
