import os
import asyncio
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("TG_TOKEN")
ATERNOS_USER = os.getenv("ATERNOS_USER")
ATERNOS_PASS = os.getenv("ATERNOS_PASS")
ALLOWED_USER_ID = int(os.getenv("USER_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Сессия для выполнения запросов к Aternos
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

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

# Функция авторизации и получения данных
def aternos_action(action_type):
    try:
        # Извлекаем ключ и значение из настроек Render
        storage_key = os.getenv("ATER_KEY")
        storage_val = os.getenv("ATER_VAL")
        
        # Передаем маркер сессии в заголовках, имитируя браузер
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Authorization": f"Bearer {storage_val}", # Передача сессии
            "Cookie": f"{storage_key}={storage_val}"
        }
        
        if action_type == "status":
            res = requests.get("https://aternos.org", headers=headers, timeout=10)
            if "online" in res.text: return "🟢 Онлайн"
            if "starting" in res.text or "loading" in res.text: return "⏳ Запускается..."
            if "stopping" in res.text: return "🛑 Выключается..."
            return "🔴 Выключен"
            
        elif action_type == "start":
            # Запрос главной страницы для вытягивания токена AJAX
            page = requests.get("https://aternos.org", headers=headers, timeout=10)
            if 'AJAX_TOKEN' in page.text:
                ajax_token = page.text.split('AJAX_TOKEN = "')[1].split('"')[0]
                # Отправка команды запуска с токеном
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
    if not is_owner(message):
        await message.answer("❌ У вас нет доступа к управлению этим сервером.")
        return
    await message.answer("👋 Привет! Я бот для прямого управления твоим сервером Aternos. Выбери действие:", reply_markup=get_main_keyboard())

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != ALLOWED_USER_ID:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return

    action = callback.data
    await callback.answer("Выполняю запрос...")

    if action == "srv_start":
        res_text = aternos_action("start")
        await callback.message.answer(res_text)
            
    elif action == "srv_stop":
        res_text = aternos_action("stop")
        await callback.message.answer(res_text)

    elif action == "srv_status":
        status = aternos_action("status")
        text = f"📊 *Состояние сервера:*\n• Статус: {status}"
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "srv_console":
        console = aternos_action("console")
        await callback.message.answer(f"💻 *Последние строки консоли:*\n```\n{console}\n```", parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
