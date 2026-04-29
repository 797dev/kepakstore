import asyncio
import os
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==========================================
# 1. SOZLAMALAR
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_TOKENINGIZ")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# ==========================================
# 2. HOLATLAR (FSM)
# ==========================================
class CheckoutState(StatesGroup):
    waiting_for_receipt = State()

class WithdrawState(StatesGroup):
    waiting_for_card = State()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_price = State()

# ==========================================
# 3. MA'LUMOTLAR BAZASI
# ==========================================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        # Foydalanuvchilar
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                referrer_id BIGINT
            )
        ''')
        # Mahsulotlar (Dinamik narxlar uchun)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                category TEXT,
                name TEXT,
                price INTEGER
            )
        ''')
        # Savat
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS cart (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                product_id INTEGER
            )
        ''')
        
        # Boshlang'ich mahsulotlarni qo'shish (agar bo'sh bo'lsa)
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        if count == 0:
            defaults = [
                ('premium', 'Telegram Premium 1 oy', 41990),
                ('premium', 'Telegram Premium 1 yil', 330000),
                ('stars', '1000 Stars', 25000),
                ('nft', 'Premium NFT Fragment', 150000),
                ('gift', 'Telegram Gift Card', 50000),
                ('mutolaa', 'Mutolaa Premium', 20000),
                ('steam', 'Steam Balans ($10)', 125000)
            ]
            for cat, name, price in defaults:
                await conn.execute("INSERT INTO products (category, name, price) VALUES ($1, $2, $3)", cat, name, price)

# ==========================================
# 4. TUGMALAR (Reply & Inline)
# ==========================================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Katalog")],
            [KeyboardButton(text="🛍️ Savatim"), KeyboardButton(text="👤 Kabinet")],
            [KeyboardButton(text="🤝 Hamkorlik"), KeyboardButton(text="📞 Aloqa")]
        ], resize_keyboard=True
    )

def get_categories_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 Telegram Premium"), KeyboardButton(text="⭐ Stars")],
            [KeyboardButton(text="🖼️ NFT"), KeyboardButton(text="🎁 Giftlar")],
            [KeyboardButton(text="📚 Mutolaa Premium"), KeyboardButton(text="🎮 Steam Balans")],
            [KeyboardButton(text="🔙 Asosiy Menyu")]
        ], resize_keyboard=True
    )

def add_to_cart_keyboard(product_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Savatga qo'shish", callback_data=f"add_{product_id}")]
    ])

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Xabar yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ Narxlarni tahrirlash", callback_data="admin_prices")]
    ])

# ==========================================
# 5. ASOSIY MANTIQ (Foydalanuvchi)
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username
    
    referrer_id = None
    if command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id != user_id:
            referrer_id = ref_id

    async with db_pool.acquire() as conn:
        user_exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
        if not user_exists:
            await conn.execute(
                "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3)",
                user_id, username, referrer_id
            )

    text = f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\nKepak Store botiga xush kelibsiz."
    await message.answer(text, reply_markup=get_main_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "🔙 Asosiy Menyu")
async def back_to_main(message: Message):
    await message.answer("Asosiy menyuga qaytdingiz.", reply_markup=get_main_menu())

@dp.message(F.text == "📞 Aloqa")
async def contact_admin(message: Message):
    text = "Savol va takliflar bo'yicha markaziy administratorga murojaat qiling:\n\n👉 <b><a href='t.me/admin_havolasi'>Adminga yozish</a></b>"
    await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# --- Katalog va Kategoriyalar ---
@dp.message(F.text == "🛒 Katalog")
async def show_catalog(message: Message):
    await message.answer("Kategoriyani tanlang:", reply_markup=get_categories_menu())

CATEGORY_MAP = {
    "💎 Telegram Premium": "premium",
    "⭐ Stars": "stars",
    "🖼️ NFT": "nft",
    "🎁 Giftlar": "gift",
    "📚 Mutolaa Premium": "mutolaa",
    "🎮 Steam Balans": "steam"
}

@dp.message(F.text.in_(CATEGORY_MAP.keys()))
async def show_category_products(message: Message):
    category_slug = CATEGORY_MAP[message.text]
    async with db_pool.acquire() as conn:
        products = await conn.fetch("SELECT id, name, price FROM products WHERE category = $1", category_slug)
    
    if not products:
        await message.answer("Bu bo'limda hozircha mahsulotlar yo'q.")
        return

    for p in products:
        text = f"<b>{p['name']}</b>\nNarxi: {p['price']:,} so'm"
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=add_to_cart_keyboard(p['id']))

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(call: CallbackQuery):
    product_id = int(call.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO cart (user_id, product_id) VALUES ($1, $2)", call.from_user.id, product_id)
    await call.answer("✅ Savatga qo'shildi!", show_alert=False)

# --- Savat va To'lov ---
@dp.message(F.text == "🛍️ Savatim")
async def show_cart(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        items = await conn.fetch('''
            SELECT p.name, p.price FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = $1
        ''', user_id)
    
    if not items:
        await message.answer("Savatingiz bo'sh. Xaridni boshlash uchun Katalogga o'ting.")
        return

    total = sum(item['price'] for item in items)
    items_text = "\n".join([f"▪️ {item['name']} - {item['price']:,} so'm" for item in items])
    
    text = (
        f"<b>Sizning savatingiz:</b>\n\n{items_text}\n\n"
        f"<b>Jami:</b> {total:,} so'm\n\n"
        "💳 <i>To'lov qilish uchun chekni (rasm ko'rinishida) yuboring. Karta: 8600 1234 5678 9012</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
    await state.update_data(total=total, items_text=items_text)
    await state.set_state(CheckoutState.waiting_for_receipt)

@dp.message(CheckoutState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    total = data.get('total', 0)
    items_text = data.get('items_text', 'Noma\'lum')
    
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    
    admin_text = (
        f"🔔 <b>Yangi to'lov!</b>\n"
        f"👤 Mijoz: {username}\n\n"
        f"🛒 <b>Mahsulotlar:</b>\n{items_text}\n\n"
        f"💰 <b>Jami summa:</b> {total:,} so'm"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{user_id}_{total}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{user_id}")]
    ])
    
    await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await message.answer("✅ Chek qabul qilindi. Admin tasdiqlashi bilan xarid amalga oshadi.", reply_markup=get_main_menu())
    await state.clear()

# --- Kabinet va Hamkorlik (Qisqartirilgan, oldingi mantiq saqlangan) ---
@dp.message(F.text == "👤 Kabinet")
async def show_cabinet(message: Message):
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", message.from_user.id)
    text = f"<b>Kabinetingiz</b>\n\n🆔 ID: <code>{message.from_user.id}</code>\n💰 Balans: <b>{(balance or 0):,} so'm</b>"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "🤝 Hamkorlik")
async def show_affiliate(message: Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"<b>5% Cashback Dasturi</b>\n\n🔗 Havolangiz:\n<code>{ref_link}</code>", parse_mode=ParseMode.HTML)

# ==========================================
# 6. ADMIN PANEL (Yangi qo'shilgan)
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👨‍💻 <b>Admin Panel</b>\n\nKerakli bo'limni tanlang:", reply_markup=admin_panel_keyboard(), parse_mode=ParseMode.HTML)

# --- Xabar yuborish ---
@dp.callback_query(F.data == "admin_broadcast")
async def ask_broadcast_msg(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("📝 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting (Rasm/Video qo'shish mumkin):")
    await state.set_state(AdminState.waiting_for_broadcast)
    await call.answer()

@dp.message(AdminState.waiting_for_broadcast)
async def send_broadcast(message: Message, state: FSMContext):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    
    count = 0
    for u in users:
        try:
            await message.copy_to(chat_id=u['user_id'])
            count += 1
            await asyncio.sleep(0.05) # Telegram limitlariga tushmaslik uchun
        except:
            pass
            
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga muvaffaqiyatli yuborildi.")
    await state.clear()

# --- Narxlarni o'zgartirish ---
@dp.callback_query(F.data == "admin_prices")
async def list_prices_for_admin(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    async with db_pool.acquire() as conn:
        products = await conn.fetch("SELECT id, name, price FROM products ORDER BY id")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for p in products:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"✏️ {p['name']} ({p['price']:,})", callback_data=f"editprice_{p['id']}")])
    
    await call.message.answer("O'zgartirmoqchi bo'lgan mahsulotingizni tanlang:", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data.startswith("editprice_"))
async def ask_new_price(call: CallbackQuery, state: FSMContext):
    prod_id = int(call.data.split("_")[1])
    await state.update_data(edit_product_id=prod_id)
    await call.message.answer("💰 Yangi narxni faqat raqamlarda kiriting (masalan: 45000):")
    await state.set_state(AdminState.waiting_for_price)
    await call.answer()

@dp.message(AdminState.waiting_for_price)
async def update_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
        
    data = await state.get_data()
    prod_id = data['edit_product_id']
    new_price = int(message.text)
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE products SET price = $1 WHERE id = $2", new_price, prod_id)
        
    await message.answer("✅ Narx muvaffaqiyatli yangilandi!")
    await state.clear()

# ==========================================
# 7. TASDIQLASH MANTIQI
# ==========================================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    data = call.data.split("_")
    user_id = int(data[1])
    amount = int(data[2])
    
    await bot.send_message(user_id, "🎉 To'lovingiz tasdiqlandi! Tez orada buyurtmangiz yetkaziladi.")
    
    # 5% Bonus va Savatni tozalash
    bonus = int(amount * 0.05)
    async with db_pool.acquire() as conn:
        referrer_id = await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
        if referrer_id:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", bonus, referrer_id)
            await bot.send_message(referrer_id, f"💸 Taklif qilgan do'stingiz xarid qildi! Balansingizga <b>{bonus:,} so'm</b> qo'shildi.", parse_mode=ParseMode.HTML)
        # Mijoz xarid qilgach savatni tozalash
        await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id)
            
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>TASDIQLANGAN</b>", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id) # Savat tozalanadi
        
    await bot.send_message(user_id, "❌ To'lovingiz rad etildi. Iltimos, adminga yozing.")
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ <b>RAD ETILGAN</b>", parse_mode=ParseMode.HTML)

# ==========================================
# 8. ISHGA TUSHIRISH
# ==========================================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
