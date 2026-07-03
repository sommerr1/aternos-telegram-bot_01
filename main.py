import os
import re
import asyncio
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ИМПОРТИРУЕМ curl_cffi ДЛЯ ОБХОДА CLOUDFLARE
from curl_cffi import requests as curl_requests

TOKEN = os.getenv("TG_TOKEN")
ALLOWED_USER_ID = int(os.getenv("USER_ID", 0))

# --- НАСТРОЙКА ПРОКСИ (ПРИ НЕОБХОДИМОСТИ) ---
# Если даже curl_cffi получит 403, впишите сюда свой прокси (SOCKS5 или HTTP)
# Пример формата: "http://user:password@proxy_address:port"
PROXY_URL = None 

COOKIES_DIR = "session_data"
os.makedirs(COOKIES_DIR, exist_ok=True)

COOKIE_FILES = {
    "session_name": os.path.join(COOKIES_DIR, "session_name.txt"),
    "session_val": os.path.join(COOKIES_DIR, "session_val.txt"),
    "gamera_user_id": os.path.join(COOKIES_DIR, "gamera_user.txt"),
    "uid": os.path.join(COOKIES_DIR, "uid.txt")
}

class SessionStates(StatesGroup):
    waiting_for_session_name = State()
    waiting_for_session_val = State()
    waiting_for_gamera = State()
    waiting_for_uid = State()

class FakeWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_fake_web_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), FakeWebHandler)
    server.serve_forever()

def load_stored_data():
    data = {}
    for key, file_path in COOKIE_FILES.items():
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data[key] = f.read().strip()
        else:
            data[key] = ""
    return data

def save_stored_value(key, value):
    file_path = COOKIE_FILES[key]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(value.strip())

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def is_owner(message: types.Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запустить", callback_data="srv_start")
    builder.button(text="⏹️ Остановить", callback_data="srv_stop")
    builder.button(text="📊 Статус", callback_data="srv_status")
    builder.button(text="💻 Консоль", callback_data="srv_console")
    builder.button(text="🔑 Настроить сессию (4 шага)", callback_data="srv_settings")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="srv_cancel_input")
    return builder.as_markup()

def aternos_action(action_type):
    try:
        data = load_stored_data()
        if not all(data.values()):
            return "⚠️ Данные авторизации не заполнены! Пройдите настройку из 4 шагов."

        cookies = {
            data["session_name"]: data["session_val"],
            "gamera_user_id": data["gamera_user_id"],
            "uid": data["uid"]
        }

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://aternos.org",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        # Используем Session из curl_cffi с имперсонацией браузера Chrome
        session = curl_requests.Session(impersonate="chrome120")
        session.cookies.update(cookies)
        
        # Конфигурируем прокси, если переменная заполнена
        if PROXY_URL:
            session.proxies = {"http": PROXY_URL, "https": PROXY_URL}

        page = session.get("https://aternos.org", headers=headers, timeout=15)
        
        if page.status_code == 403:
            return "❌ Ошибка 403: Cloudflare жестко заблокировал IP вашего хостинга. Требуется подключение прокси."
        
        token_match = re.search(r'window\.ATERNOS_SEC_TOKEN\s*=\s*"([a-zA-Z0-9]+)"', page.text)
        if not token_match:
            return "⚠️ Токен безопасности (SEC_TOKEN) не найден в коде. Возможно, сессия устарела."
        sec_token = token_match.group(1)
        
        if action_type == "status":
            if "statuslabel-live" in page.text: return "🟢 Онлайн"
            if "statuslabel-loading" in page.text or "statuslabel-preparing" in page.text: return "⏳ Запускается..."
            if "statuslabel-stopping" in page.text: return "🛑 Выключается..."
            return "🔴 Выключен"
            
        elif action_type in ["start", "stop"]:
            ajax_action = "start" if action_type == "start" else "stop"
            action_url = f"https://aternos.org{ajax_action}.php"
            
            res = session.post(action_url, params={"SEC": sec_token}, headers=headers, timeout=15)
            if res.status_code == 200:
                return "🚀 Запрос на запуск отправлен!" if action_type == "start" else "🛑 Сигнал на остановку отправлен."
            return f"⚠️ Ошибка выполнения операции. Код ответа: {res.status_code}"
            
        elif action_type == "console":
            log_url = "https://aternos.orglog.php"
            res = session.get(log_url, params={"SEC": sec_token}, headers=headers, timeout=15)
            if res.status_code == 200:
                try:
                    log_data = res.json().get("log", "Консоль пуста.")
                    lines = log_data.split("\n")[-15:]
                    return "\n".join(lines)
                except:
                    return "⚠️ Ошибка разбора логов сервера."
            return "⚠️ Не удалось получить данные логов."
            
    except Exception as e:
        return f"❌ Крит. ошибка структуры запроса: {str(e)}"

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    await state.clear()
    await message.answer("👋 Меню управления сервером Aternos (Имперсонация Chrome):", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "srv_cancel_input")
async def cancel_input(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    await state.clear()
    await callback.answer("Ввод отменен")
    await callback.message.edit_text("⚙️ Ввод данных прерван. Главное меню:", reply_markup=get_main_keyboard())

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    action = callback.data
    
    if action.startswith("srv_") and action != "srv_settings":
        await callback.answer("Запрос выполняется...")
        act = action.replace("srv_", "")
        res_text = aternos_action(act)
        
        if act == "status":
            await callback.message.answer(f"📊 *Состояние服务器:*\n• Статус: {res_text}", parse_mode="Markdown")
        elif act == "console":
            await callback.message.answer(f"💻 *Последние строки консоли:*\n```\n{res_text}\n```", parse_mode="Markdown")
        else:
            await callback.message.answer(res_text)
        
    elif action == "srv_settings":
        await callback.answer()
        await state.set_state(SessionStates.waiting_for_session_name)
        await callback.message.edit_text(
            "🔑 *Настройка (Шаг 1 из 4)*\n\nОтправьте **ИМЯ** сессионной куки (например, `ATERNOS_SESSION`):",
            parse_mode="Markdown", reply_markup=get_cancel_keyboard()
        )

@dp.message(StateFilter(SessionStates.waiting_for_session_name))
async def process_session_name(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_stored_value("session_name", message.text)
    await state.set_state(SessionStates.waiting_for_session_val)
    await message.answer(
        "✅ Имя принято.\n\n*Шаг 2 из 4*: Теперь отправьте **ЗНАЧЕНИЕ** этой сессионной куки:",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_session_val))
async def process_session_val(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_stored_value("session_val", message.text)
    await state.set_state(SessionStates.waiting_for_gamera)
    await message.answer(
        "✅ Значение принято.\n\n*Шаг 3 из 4*: Отправьте значение для куки:\n`gamera_user_id`",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_gamera))
async def process_gamera(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_stored_value("gamera_user_id", message.text)
    await state.set_state(SessionStates.waiting_for_uid)
    await message.answer(
        "✅ Принято.\n\n*Шаг 4 из 4*: Отправьте значение для куки:\n`uid`",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_uid))
async def process_uid(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_stored_value("uid", message.text)
    await state.clear()
    await message.answer("🎉 Все параметры успешно перезаписаны на клиенте с TLS-обходом!", reply_markup=get_main_keyboard())

async def main():
    Thread(target=run_fake_web_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
