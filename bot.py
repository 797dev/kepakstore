import asyncio
import os
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==========================================
# 1. SOZLAMALAR VA O'ZGARUVCHILAR
# ==========================================
# Railway "Variables" bo'limiga ushbu o'zgaruvchilarni qo'shasiz
BOT_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_TOKENINGIZ")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789)) # O'zingizning ID raqamingiz
DATABASE_URL = os.getenv("DATABASE_URL") # Railway avtomat beradi

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# ==========================================
# 2. HOLATLAR (FSM - Kutish jarayonlari)
# ==========================================
class CheckoutState(StatesGroup):
    waiting_for_receipt = State()

class WithdrawState(StatesGroup):
    waiting_for_card = State()

# ==========================================
# 3. MA'LUMOTLAR BAZASI (PostgreSQL)
# ==========================================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        # Foydalanuvchilar jadvali
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                referrer_id BIGINT
            )
        ''')

# ==========================================
# 4. TUGMALAR (Apple-style minimalizm)
# ==========================================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Katalog")],
            [KeyboardButton(text="🛍️ Savatim"), KeyboardButton(text="👤 Kabinet")],
            [KeyboardButton(text="🤝 Hamkorlik"), KeyboardButton(text="📞 Aloqa")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Bo'limni tanlang..."
    )

def admin_confirm_keyboard(user_id: int, order_amount: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{user_id}_{order_amount}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{user_id}")]
    ])

def withdraw_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pulni yechib olish", callback_data="withdraw_funds")]
    ])

# ==========================================
# 5. ASOSIY MANTIQ VA HANDLERLAR
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Referal ID ni aniqlash (hech qanday blokirovka va anti-cheatsiz)
    referrer_id = None
    if command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id != user_id:
            referrer_id = ref_id

    # Bazaga yozish (agar mavjud bo'lmasa)
    async with db_pool.acquire() as conn:
        user_exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
        if not user_exists:
            await conn.execute(
                "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3)",
                user_id, username, referrer_id
            )

    text = (
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
        "Kepak Store botiga xush kelibsiz. Raqamli mahsulotlarni qulay va tez xarid qiling."
    )
    await message.answer(text, reply_markup=get_main_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "📞 Aloqa")
async def contact_admin(message: Message):
    text = "Savol va takliflar bo'yicha markaziy administratorga murojaat qiling:\n\n👉 <b>Adminga yozish</b>"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "🛒 Katalog")
async def show_catalog(message: Message):
    # Katalog namunasi. Dizayn ochiq va keng.
    text = (
        "<b>Telegram Premium (1 oylik)</b>\n"
        "Narxi: 41,990 so'm\n\n"
        "<i>Xaridni amalga oshirish uchun 'Savatim' bo'limiga o'ting.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "🛍️ Savatim")
async def show_cart(message: Message, state: FSMContext):
    # Savat jarayonini boshlash
    text = (
        "<b>Sizning savatingiz:</b>\n"
        "1x Telegram Premium 1 oy — 41,990 so'm\n\n"
        "<b>Jami:</b> 41,990 so'm\n\n"
        "💳 <i>To'lov qilish uchun Click/Payme orqali quyidagi kartaga pul o'tkazing va chekni (rasm ko'rinishida) yuboring:</i>\n\n"
        "<code>8600 1234 5678 9012</code>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
    await state.set_state(CheckoutState.waiting_for_receipt)

@dp.message(CheckoutState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    
    # Adminga yuborish
    admin_text = (
        f"🔔 <b>Yangi to'lov!</b>\n"
        f"👤 Mijoz: {username}\n"
        f"💰 Summa: 41,990 so'm\n"
        f"🛒 Mahsulot: Telegram Premium 1 oy"
    )
    
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=admin_text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_confirm_keyboard(user_id, 41990)
    )
    
    await message.answer("✅ Chek qabul qilindi. Admin tasdiqlashi bilan xarid amalga oshadi.", reply_markup=get_main_menu())
    await state.clear()

@dp.message(F.text == "🤝 Hamkorlik")
async def show_affiliate(message: Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    async with db_pool.acquire() as conn:
        ref_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", message.from_user.id)
    
    text = (
        "<b>Hamkorlik dasturi (5% Cashback)</b>\n\n"
        "Do'stlaringizni taklif qiling va ular sarflagan summadan <b>5% bonus</b> oling.\n\n"
        f"🔗 <b>Sizning havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        f"👥 Taklif qilinganlar: {ref_count} kishi"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "👤 Kabinet")
async def show_cabinet(message: Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
        if balance is None: balance = 0
        
    text = (
        "<b>Sizning kabinetingiz</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Balans: <b>{balance:,.0f} so'm</b>\n\n"
        "<i>Balansingizdagi mablag'ni karta orqali yechib olishingiz mumkin.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=withdraw_keyboard())

# --- Yechib olish (Withdraw) Mantiqi ---
@dp.callback_query(F.data == "withdraw_funds")
async def ask_for_card(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
    
    if not balance or balance <= 0:
        await call.answer("Kechirasiz, balansingizda yetarli mablag' yo'q.", show_alert=True)
        return
        
    await call.message.answer("💳 <b>Karta raqamingizni yuboring (16 ta raqam):</b>", parse_mode=ParseMode.HTML)
    await state.set_state(WithdrawState.waiting_for_card)
    await call.answer()

@dp.message(WithdrawState.waiting_for_card)
async def process_withdraw(message: Message, state: FSMContext):
    card_number = message.text
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
        # Balansni nolga tushirish (muzlatish mantiqi)
        await conn.execute("UPDATE users SET balance = 0 WHERE user_id = $1", user_id)
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    admin_text = (
        f"💸 <b>Pul yechish so'rovi!</b>\n"
        f"👤 Mijoz: {username}\n"
        f"💰 Summa: {balance:,.0f} so'm\n"
        f"💳 Karta: <code>{card_number}</code>"
    )
    
    await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode=ParseMode.HTML)
    await message.answer("✅ So'rov adminga yuborildi. Pul tez orada kartangizga tushirib beriladi.")
    await state.clear()

# --- Admin Tasdiqlash Mantiqi ---
@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    data = call.data.split("_")
    user_id = int(data[1])
    amount = int(data[2])
    
    # 1. Mijozga xabar
    await bot.send_message(user_id, "🎉 To'lovingiz tasdiqlandi! Tez orada buyurtmangiz yetkaziladi.")
    
    # 2. Referalga 5% bonus yozish
    bonus = int(amount * 0.05)
    async with db_pool.acquire() as conn:
        referrer_id = await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
        if referrer_id:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", bonus, referrer_id)
            await bot.send_message(
                referrer_id, 
                f"💸 Siz taklif qilgan do'stingiz xarid qildi. Balansingizga <b>{bonus:,.0f} so'm</b> qo'shildi!",
                parse_mode=ParseMode.HTML
            )
            
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>TASDIQLANGAN</b>", parse_mode=ParseMode.HTML)
    await call.answer("Tasdiqlandi va bonus yozildi!")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])
    await bot.send_message(user_id, "❌ Kechirasiz, to'lovingiz tasdiqlanmadi. Qayta urinib ko'ring yoki adminga yozing.")
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ <b>RAD ETILGAN</b>", parse_mode=ParseMode.HTML)
    await call.answer("Rad etildi!")

# ==========================================
# 6. ISHGA TUSHIRISH (MAIN)
# ==========================================
async def main():
    await init_db()
    print("Bot muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
