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

KEY_FILE = "session_user.txt"
VAL_FILE = "session_cookie.txt"

DEFAULT_KEY = "ваш_user_id_из_куки"
DEFAULT_VAL = "ваш_длинный_токен_сессии"

# --- СОСТОЯНИЯ ДЛЯ ОЖИДАНИЯ ВВОДА СЕССИИ ---
class SessionStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_session_token = State()

# --- ХИТРОСТЬ ДЛЯ ОБХОДА ОШИБКИ PORT TIMEOUT НА RENDER ---
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
# --------------------------------------------------------

def init_session_files():
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(DEFAULT_KEY)
    if not os.path.exists(VAL_FILE):
        with open(VAL_FILE, "w", encoding="utf-8") as f: f.write(DEFAULT_VAL)

def get_current_session():
    init_session_files()
    with open(KEY_FILE, "r", encoding="utf-8") as f: s_user = f.read().strip()
    with open(VAL_FILE, "r", encoding="utf-8") as f: s_session = f.read().strip()
    return s_user, s_session

bot = Bot(token=TOKEN)
# Добавляем MemoryStorage для работы состояний FSM
dp = Dispatcher(storage=MemoryStorage())

def is_owner(message: types.Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запустить", callback_data="srv_start")
    builder.button(text="⏹️ Остановить", callback_data="srv_stop")
    builder.button(text="📊 Статус", callback_data="srv_status")
    builder.button(text="💻 Консоль", callback_data="srv_console")
    builder.button(text="🔑 Настройки сессии", callback_data="srv_settings")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="srv_cancel_input")
    return builder.as_markup()

def aternos_action(action_type):
    try:
        sec_user, sec_session = get_current_session()
        
        cookies = {
            "ATERNOS_SEC_USER": sec_user,
            "ATERNOS_SEC_SESSION": sec_session
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://aternos.org"
        }
        
        session = requests.Session()
        page = session.get("https://aternos.org", headers=headers, cookies=cookies, timeout=10)
        
        if page.status_code == 403:
            return "❌ Ошибка 403: Сессия устарела или заблокирована Cloudflare."
        
        token_match = re.search(r'window\.ATERNOS_SEC_TOKEN\s*=\s*"([a-zA-Z0-9]+)"', page.text)
        if not token_match:
            return "⚠️ Не удалось извлечь токен безопасности. Обновите сессию."
        sec_token = token_match.group(1)
        
        if action_type == "status":
            if "statuslabel-live" in page.text: return "🟢 Онлайн"
            if "statuslabel-loading" in page.text or "statuslabel-preparing" in page.text: return "⏳ Запускается..."
            if "statuslabel-stopping" in page.text: return "🛑 Выключается..."
            return "🔴 Выключен"
            
        elif action_type in ["start", "stop"]:
            ajax_action = "start" if action_type == "start" else "stop"
            action_url = f"https://aternos.org{ajax_action}.php"
            params = {"SEC": sec_token}
            
            res = session.post(action_url, params=params, headers=headers, cookies=cookies, timeout=10)
            if res.status_code == 200:
                return "🚀 Запрос на запуск отправлен!" if action_type == "start" else "🛑 Сигнал на остановку отправлен."
            return f"⚠️ Ошибка выполнения. Код ответа: {res.status_code}"
            
        elif action_type == "console":
            log_url = "https://aternos.orglog.php"
            res = session.get(log_url, params={"SEC": sec_token}, headers=headers, cookies=cookies, timeout=10)
            if res.status_code == 200:
                try:
                    log_data = res.json().get("log", "Консоль пуста.")
                    lines = log_data.split("\n")[-15:]
                    return "\n".join(lines)
                except:
                    return "⚠️ Ошибка парсинга логов."
            return "⚠️ Не удалось загрузить консоль."
            
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    await state.clear()  # Сбрасываем любые состояния при вызове /start
    await message.answer("👋 Меню управления сервером Aternos:", reply_markup=get_main_keyboard())

# --- ОБРАБОТКА ИНЛАЙН КНОПОК ---
@dp.callback_query(F.data == "srv_cancel_input")
async def cancel_input(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    await state.clear()
    await callback.answer("Ввод отменен")
    await callback.message.edit_text("⚙️ Действие отменено. Главное меню:", reply_markup=get_main_keyboard())

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ALLOWED_USER_ID: return
    action = callback.data
    
    if action == "srv_start":
        await callback.answer("Выполняю запрос...")
        await callback.message.answer(aternos_action("start"))
    elif action == "srv_stop":
        await callback.answer("Выполняю запрос...")
        await callback.message.answer(aternos_action("stop"))
    elif action == "srv_status":
        await callback.answer("Выполняю запрос...")
        status = aternos_action("status")
        await callback.message.answer(f"📊 *Состояние сервера:*\n• Статус: {status}", parse_mode="Markdown")
    elif action == "srv_console":
        await callback.answer("Выполняю запрос...")
        console = aternos_action("console")
        await callback.message.answer(f"💻 *Последние строки консоли:*\n```\n{console}\n```", parse_mode="Markdown")
        
    elif action == "srv_settings":
        await callback.answer()
        sec_user, _ = get_current_session()
        text = (
            f"🔑 *Настройки сессии Aternos*\n\n"
            f"Текущий пользователь ID: `{sec_user}`\n\n"
            f"Шаг 1: Пожалуйста, отправьте новое значение для куки *ATERNOS\_SEC\_USER*."
        )
        await state.set_state(SessionStates.waiting_for_user_id)
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_cancel_keyboard())

# --- ПОШАГОВЫЙ ИНТЕРАКТИВНЫЙ ВВОД ДАННЫХ (FSM) ---
@dp.message(StateFilter(SessionStates.waiting_for_user_id))
async def process_user_id(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    
    # Сохраняем введенный USER ID во временное хранилище бота
    await state.update_data(new_user_id=message.text.strip())
    
    await state.set_state(SessionStates.waiting_for_session_token)
    await message.answer(
        "✅ ID пользователя получен.\n\nШаг 2: Теперь отправьте новое значение для куки *ATERNOS\_SEC\_SESSION* (длинный токен).",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(StateFilter(SessionStates.waiting_for_session_token))
async def process_session_token(message: types.Message, state: FSMContext):
    if not is_owner(message): return
    
    # Получаем сохраненный ранее USER ID и текущий токен
    user_data = await state.get_data()
    new_user_id = user_data.get("new_user_id")
    new_session_token = message.text.strip()
    
    try:
        # Записываем новые данные в файлы сессий
        with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(new_user_id)
        with open(VAL_FILE, "w", encoding="utf-8") as f: f.write(new_session_token)
        
        await state.clear() # Сбрасываем состояние, возвращаемся в обычный режим
        await message.answer("🎉 Сессия успешно обновлена и сохранена в файлы!", reply_markup=get_main_keyboard())
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при сохранении сессии: {str(e)}", reply_markup=get_main_keyboard())

async def main():
    init_session_files()
    Thread(target=run_fake_web_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
