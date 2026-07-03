import os
import re
import asyncio
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("TG_TOKEN")
ALLOWED_USER_ID = int(os.getenv("USER_ID", 0))

# Файлы для хранения всех 4 кук
COOKIES_DIR = "session_data"
os.makedirs(COOKIES_DIR, exist_ok=True)

COOKIE_FILES = {
    "ATERNOS_SEC_USER": os.path.join(COOKIES_DIR, "sec_user.txt"),
    "ATERNOS_SEC_SESSION": os.path.join(COOKIES_DIR, "sec_session.txt"),
    "xf_user": os.path.join(COOKIES_DIR, "xf_user.txt"),
    "xf_session": os.path.join(COOKIES_DIR, "xf_session.txt")
}

# --- НАСТРОЙКА FSM ДЛЯ ПОШАГОВОГО ВВОДА ---
class SessionStates(StatesGroup):
    waiting_for_sec_user = State()
    waiting_for_sec_session = State()
    waiting_for_xf_user = State()
    waiting_for_xf_session = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER PORT TIMEOUT ---
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

# --- ЛОГИКА РАБОТЫ С КУКАМИ ---
def load_cookies():
    loaded = {}
    for key, file_path in COOKIE_FILES.items():
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                loaded[key] = f.read().strip()
        else:
            loaded[key] = ""
    return loaded

def save_cookie_value(key, value):
    file_path = COOKIE_FILES[key]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(value.strip())

# --- КНОПКИ И МЕНЮ ---
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
    builder.button(text="🔑 Настроить куки (4 шт)", callback_data="srv_settings")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="srv_cancel_input")
    return builder.as_markup()

# --- ВЗАИМОДЕЙСТВИЕ С ATERNOS ---
def aternos_action(action_type):
    try:
        current_cookies = load_cookies()
        
        # Проверяем заполненность данных
        if not all(current_cookies.values()):
            return "⚠️ Настроены не все куки! Нажмите кнопку 'Настроить куки' в меню."

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://aternos.org",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
        
        session = requests.Session()
        # Загружаем полную сессию со всеми предоставленными куками
        session.cookies.update(current_cookies)
        
        # Шаг 1. Переход на страницу сервера для обновления токенов авторизации
        page = session.get("https://aternos.org", headers=headers, timeout=10)
        
        if page.status_code == 403:
            return "❌ Ошибка 403: Защита Cloudflare отклонила запрос. Обновите ВСЕ 4 куки свежими значениями из браузера."
        
        # Парсим токен сессии (SEC_TOKEN)
        token_match = re.search(r'window\.ATERNOS_SEC_TOKEN\s*=\s*"([a-zA-Z0-9]+)"', page.text)
        if not token_match:
            return "⚠️ Сессия не авторизована (Токен безопасности не найден). Перезапишите куки."
        sec_token = token_match.group(1)
        
        # Шаг 2. Обработка действий панели управления
        if action_type == "status":
            if "statuslabel-live" in page.text: return "🟢 Онлайн"
            if "statuslabel-loading" in page.text or "statuslabel-preparing" in page.text: return "⏳ Запускается..."
            if "statuslabel-stopping" in page.text: return "🛑 Выключается..."
            return "🔴 Выключен"
            
        elif action_type in ["start", "stop"]:
            ajax_action = "start" if action_type == "start" else "stop"
            action_url = f"https://aternos.org{ajax_action}.php"
            
            res = session.post(action_url, params={"SEC": sec_token}, headers=headers, timeout=10)
            if res.status_code == 200:
                return "🚀 Запрос на запуск отправлен!" if action_type == "start" else "🛑 Сигнал на остановку отправлен."
            return f"⚠️ Ошибка выполнения PHP. Код ответа: {res.status_code}"
            
        elif action_type == "console":
            log_url = "https://aternos.orglog.php"
            res = session.get(log_url, params={"SEC": sec_token}, headers=headers, timeout=10)
            if res.status_code == 200:
                try:
                    log_data = res.json().get("log", "Консоль пуста.")
                    lines = log_data.split("\n")[-15:]
                    return "\n".join(lines)
                except:
                    return "⚠️ Ошибка разбора лог-файла."
            return "⚠️ Не удалось получить данные консоли."
            
    except Exception as e:
        return f"❌ Крит. ошибка: {str(e)}"

# --- ХЕНДЛЕРЫ КОМАНД ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    await state.clear()
    await message.answer("👋 Меню управления сервером Aternos (Синхронизация через 4 куки):", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "srv_cancel_input")
async def cancel_input(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    await state.clear()
    await callback.answer("Ввод отменен")
    await callback.message.edit_text("⚙️ Ввод кук прерван. Главное меню:", reply_markup=get_main_keyboard())

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    action = callback.data
    
    if action.startswith("srv_") and action != "srv_settings":
        await callback.answer("Запрос выполняется...")
        act = action.replace("srv_", "")
        res_text = aternos_action(act)
        
        if act == "status":
            await callback.message.answer(f"📊 *Состояние сервера:*\n• Статус: {res_text}", parse_mode="Markdown")
        elif act == "console":
            await callback.message.answer(f"💻 *Последние строки консоли:*\n```\n{res_text}\n```", parse_mode="Markdown")
        else:
            await callback.message.answer(res_text)
        
    elif action == "srv_settings":
        await callback.answer()
        await state.set_state(SessionStates.waiting_for_sec_user)
        await callback.message.edit_text(
            "🔑 *Настройка кук сессии (Шаг 1 из 4)*\n\nОтправьте текстовым сообщением значение для куки:\n`ATERNOS_SEC_USER`",
            parse_mode="Markdown", reply_markup=get_cancel_keyboard()
        )

# --- ПОШАГОВЫЙ ИНТЕРФЕЙС НАСТРОЙКИ СЕССИИ (FSM) ---
@dp.message(StateFilter(SessionStates.waiting_for_sec_user))
async def process_sec_user(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_cookie_value("ATERNOS_SEC_USER", message.text)
    await state.set_state(SessionStates.waiting_for_sec_session)
    await message.answer(
        "✅ Принято.\n\n*Шаг 2 из 4*: Отправьте значение для куки:\n`ATERNOS_SEC_SESSION`",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_sec_session))
async def process_sec_session(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_cookie_value("ATERNOS_SEC_SESSION", message.text)
    await state.set_state(SessionStates.waiting_for_xf_user)
    await message.answer(
        "✅ Принято.\n\n*Шаг 3 из 4*: Отправьте значение для куки:\n`xf_user`",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_xf_user))
async def process_xf_user(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_cookie_value("xf_user", message.text)
    await state.set_state(SessionStates.waiting_for_xf_session)
    await message.answer(
        "✅ Принято.\n\n*Шаг 4 из 4*: Отправьте финальное значение куки:\n`xf_session`",
        parse_mode="Markdown", reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_xf_session))
async def process_xf_session(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    save_cookie_value("xf_session", message.text)
    await state.clear()
    await message.answer("🎉 Полная сессия из 4 кук успешно обновлена и сохранена на сервере!", reply_markup=get_main_keyboard())

# --- ЗАПУСК ---
async def main():
    Thread(target=run_fake_web_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
