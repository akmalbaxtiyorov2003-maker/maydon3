import asyncio
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= SOZLAMALAR =================
# Token va admin ID Render'ning Environment bo'limidan olinadi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6009230275"))   # stadion egasining Telegram ID si
OPEN_HOUR = 19                                        # ochilish soati (19:00)
CLOSE_HOUR = 5                                        # yopilish soati (05:00, ertasi kuni)
PRICE = "130 000 so'm / soat"
DB_FILE = os.getenv("DB_PATH", "bookings.db")
PORT = int(os.getenv("PORT", "10000"))                # Render uchun
# ==============================================

# Ish soatlari: 19,20,21,22,23,0,1,2,3,4
if CLOSE_HOUR <= OPEN_HOUR:
    HOURS = list(range(OPEN_HOUR, 24)) + list(range(0, CLOSE_HOUR))
else:
    HOURS = list(range(OPEN_HOUR, CLOSE_HOUR))

router = Router()


def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS bookings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                phone TEXT,
                day TEXT,
                hour INTEGER,
                UNIQUE(day, hour)
            )"""
        )


def hour_label(h: int) -> str:
    moon = " 🌙" if h < OPEN_HOUR and CLOSE_HOUR <= OPEN_HOUR else ""
    return f"{h:02d}:00{moon}"


class Book(StatesGroup):
    name = State()
    phone = State()


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="⚽ Vaqt bron qilish", callback_data="book")
    kb.button(text="📋 Mening bronlarim", callback_data="my")
    kb.adjust(1)
    return kb.as_markup()


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        f"Assalomu alaykum! ⚽ Stadionga xush kelibsiz.\n"
        f"🕖 Ish vaqti: {OPEN_HOUR:02d}:00 dan {CLOSE_HOUR:02d}:00 gacha\n"
        f"💰 Narx: {PRICE}",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "book")
async def pick_day(c: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for i, label in enumerate(["Bugun", "Ertaga", "Indinga"]):
        d = date.today() + timedelta(days=i)
        kb.button(text=f"{label} ({d.strftime('%d.%m')})", callback_data=f"d:{d.isoformat()}")
    kb.adjust(1)
    await c.message.edit_text("Sanani tanlang:", reply_markup=kb.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("d:"))
async def pick_hour(c: CallbackQuery):
    day = c.data.split(":", 1)[1]
    with db() as conn:
        taken = {r[0] for r in conn.execute("SELECT hour FROM bookings WHERE day=?", (day,))}
    now_hour = datetime.now().hour
    kb = InlineKeyboardBuilder()
    for h in HOURS:
        past = day == date.today().isoformat() and OPEN_HOUR <= h <= now_hour
        if h in taken or past:
            kb.button(text=f"❌ {hour_label(h)}", callback_data="busy")
        else:
            kb.button(text=f"🟢 {hour_label(h)}", callback_data=f"h:{day}:{h}")
    kb.adjust(2)
    await c.message.edit_text(f"📅 {day} uchun bo'sh vaqtlar:", reply_markup=kb.as_markup())
    await c.answer()


@router.callback_query(F.data == "busy")
async def busy(c: CallbackQuery):
    await c.answer("Bu vaqt band yoki o'tib ketgan", show_alert=True)


@router.callback_query(F.data.startswith("h:"))
async def pick_name(c: CallbackQuery, state: FSMContext):
    _, day, hour = c.data.split(":")
    await state.update_data(day=day, hour=int(hour))
    await state.set_state(Book.name)
    await c.message.answer("Ismingizni yozing:")
    await c.answer()


@router.message(Book.name)
async def got_name(m: Message, state: FSMContext):
    if not m.text:
        return await m.answer("Iltimos, ismingizni matn qilib yozing.")
    await state.update_data(name=m.text.strip())
    await state.set_state(Book.phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await m.answer("Telefon raqamingizni yuboring yoki yozing:", reply_markup=kb)


@router.message(Book.phone)
async def got_phone(m: Message, state: FSMContext, bot: Bot):
    phone = m.contact.phone_number if m.contact else (m.text or "").strip()
    if not phone:
        return await m.answer("Iltimos, telefon raqamini yuboring.")
    data = await state.get_data()
    await state.clear()
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO bookings(user_id,name,phone,day,hour) VALUES(?,?,?,?,?)",
                (m.from_user.id, data["name"], phone, data["day"], data["hour"]),
            )
    except sqlite3.IntegrityError:
        await m.answer(
            "😔 Kechirasiz, bu vaqtni boshqa odam band qilib bo'ldi. Boshqa vaqt tanlang.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await m.answer("Menyu:", reply_markup=main_menu())
        return
    await m.answer(
        f"✅ Bron tasdiqlandi!\n📅 {data['day']}\n🕒 {hour_label(data['hour'])}\n💰 {PRICE}",
        reply_markup=ReplyKeyboardRemove(),
    )
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🆕 Yangi bron\n👤 {data['name']}\n📞 {phone}\n"
                f"📅 {data['day']}  🕒 {hour_label(data['hour'])}",
            )
        except Exception:
            logging.exception("Adminga xabar yuborib bo'lmadi")


@router.callback_query(F.data == "my")
async def my_bookings(c: CallbackQuery):
    with db() as conn:
        rows = conn.execute(
            "SELECT id,day,hour FROM bookings WHERE user_id=? AND day>=? ORDER BY day,hour",
            (c.from_user.id, date.today().isoformat()),
        ).fetchall()
    if not rows:
        await c.message.answer("Sizda faol bron yo'q.")
        return await c.answer()
    kb = InlineKeyboardBuilder()
    for bid, day, hour in rows:
        kb.button(text=f"❌ Bekor: {day} {hour_label(hour)}", callback_data=f"c:{bid}")
    kb.adjust(1)
    await c.message.answer("Bronlaringiz (bekor qilish uchun bosing):", reply_markup=kb.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("c:"))
async def cancel(c: CallbackQuery, bot: Bot):
    bid = int(c.data.split(":")[1])
    with db() as conn:
        row = conn.execute(
            "SELECT day,hour,name FROM bookings WHERE id=? AND user_id=?",
            (bid, c.from_user.id),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
    if not row:
        return await c.answer("Bron topilmadi", show_alert=True)
    await c.message.edit_text(f"Bron bekor qilindi: {row[0]} {hour_label(row[1])}")
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID, f"♻️ Bron bekor qilindi: {row[2]} — {row[0]} {hour_label(row[1])}"
            )
        except Exception:
            logging.exception("Adminga xabar yuborib bo'lmadi")
    await c.answer()


@router.message(Command("today"))
async def admin_list(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    text = ""
    with db() as conn:
        for i in (0, 1):
            d = date.today() + timedelta(days=i)
            rows = conn.execute(
                "SELECT hour,name,phone FROM bookings WHERE day=? "
                "ORDER BY (hour < ?), hour",
                (d.isoformat(), OPEN_HOUR),
            ).fetchall()
            text += f"\n📅 {d.isoformat()}\n"
            if rows:
                text += "\n".join(f"{hour_label(h)} — {n}, {p}" for h, n, p in rows)
            else:
                text += "Bron yo'q"
            text += "\n"
    await m.answer(text)


@router.message(Command("block"))
async def admin_block(m: Message):
    """Admin: /block 2026-10-25 21  — vaqtni yopish (ta'mir, turnir)"""
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, day, hour = m.text.split()
        with db() as conn:
            conn.execute(
                "INSERT INTO bookings(user_id,name,phone,day,hour) VALUES(?,?,?,?,?)",
                (m.from_user.id, "BLOK", "-", day, int(hour)),
            )
        await m.answer("🔒 Vaqt yopildi.")
    except Exception:
        await m.answer("Format: /block 2026-10-25 21\n(yoki bu vaqt allaqachon band)")


async def start_web_server():
    """Render 'Web Service' port kutadi, shuning uchun kichik server ochamiz."""
    app = web.Application()

    async def ok(_request):
        return web.Response(text="Bot ishlayapti")

    app.router.add_get("/", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. Environment'ga BOT_TOKEN qo'shing.")
    init_db()
    await start_web_server()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
