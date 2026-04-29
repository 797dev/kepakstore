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
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                referrer_id BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                category TEXT,
                name TEXT,
                price INTEGER
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS cart (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                product_id INTEGER
            )
        ''')
        
        # Eski ro'yxatni tozalab, to'liq ro'yxatni kiritish
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        if count < 20: 
            await conn.execute("DELETE FROM products")
            
            defaults = [
                # Premium
                ('premium', 'Premium 1 oy', 41990),
                ('premium', 'Premium 3 oy', 160000),
                ('premium', 'Premium 6 oy', 225000),
                ('premium', 'Premium 12 oy', 370000),
                # Stars
                ('stars', '50 Stars', 12500),
                ('stars', '100 Stars', 25000),
                ('stars', '200 Stars', 50000),
                ('stars', '500 Stars', 125000),
                ('stars', '1000 Stars', 250000),
                # NFT
                ('nft', 'Vice cream', 59990),
                ('nft', 'Ice cream', 59990),
                ('nft', 'Instant ramen', 59900),
                ('nft', 'Lunar snake', 79700),
                ('nft', 'Snake box', 79700),
                ('nft', 'Xmas stocking', 79700),
                ('nft', 'Pool float', 79700),
                ('nft', 'Whip cupcake', 79700),
                ('nft', 'Candy cane', 79700),
                ('nft', 'Winter wreath', 79700),
                ('nft', 'Chill flame', 79700),
                ('nft', 'Big year', 79700),
                ('nft', 'Hypno lollipop', 79700),
                ('nft', 'Mood pack', 79700),
                ('nft', 'Holiday drink', 79700),
                ('nft', 'Lol pop', 79700),
                # Gift (Telegram sovg'alari)
                ('gift', '🧸 15 ⭐️', 4000),
                ('gift', '🎁 25 ⭐️', 6000),
                ('gift', '🌹 25 ⭐️', 6000),
                ('gift', '🎂 50 ⭐️', 13000),
                ('gift', '🚀 50 ⭐️', 13000),
                ('gift', '🍾 50 ⭐️', 13000),
                ('gift', '💐 50 ⭐️', 13000),
                ('gift', '💎 100 ⭐️', 22000),
                ('gift', '🏆 100 ⭐️', 22000),
                ('gift', '💍 100 ⭐️', 22000),
                # Boshqalar
                ('mutolaa', 'Mutolaa 1 oy', 40000),
                ('steam', 'Steam Balans ($10)', 130000)
            ]
            for cat, name, price in defaults:
                await conn.execute("INSERT INTO products (category, name, price) VALUES ($1, $2, $3)", cat, name, price)

# ==========================================
# 4. TUGMALAR (Reply va Inline)
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

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Xabar yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ Narxlarni tahrirlash", callback_data="admin_prices")]
    ])

def withdraw_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pulni yechib olish", callback_data="withdraw_funds")]
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
        else:
            if referrer_id:
                current_ref = await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
                if not current_ref:
                    await conn.execute("UPDATE users SET referrer_id = $1 WHERE user_id = $2", referrer_id, user_id)

    text = f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\nKepak Store botiga xush kelibsiz."
    await message.answer(text, reply_markup=get_main_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "🔙 Asosiy Menyu")
async def back_to_main(message: Message):
    await message.answer("Asosiy menyuga qaytdingiz.", reply_markup=get_main_menu())

@dp.message(F.text == "📞 Aloqa")
async def contact_admin(message: Message):
    text = "Savol va takliflar bo'yicha markaziy administratorga murojaat qiling:\n\n👉 <b><a href='t.me/admin_havola'>Adminga yozish</a></b>"
    await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# --- Katalog ---
@dp.message(F.text == "🛒 Katalog")
async def show_catalog(message: Message):
    await message.answer("Qaysi bo'limdan xarid qilasiz?", reply_markup=get_categories_menu())

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
        products = await conn.fetch("SELECT id, name, price FROM products WHERE category = $1 ORDER BY id", category_slug)
    
    if not products:
        await message.answer("Bu bo'limda hozircha mahsulotlar yo'q.")
        return

    text_lines = [f"<b>{message.text}</b>\n"]
    for p in products:
        text_lines.append(f"▪️ <b>{p['name']}</b> — {p['price']:,} so'm")
    
    text = "\n".join(text_lines)
    
    if category_slug == "nft":
        text += "\n\n<i>Boshqa hamma turdagi NFTlar sizning xohishingizdagi kelishilgan narxda olib beriladi. Buning uchun 'Aloqa' bo'limi orqali admin bilan bog'laning.</i>"
        
    text += "\n\n⬇️ <i>Kerakli mahsulotni tanlang:</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for p in products:
        row.append(InlineKeyboardButton(text=f"🛒 {p['name']}", callback_data=f"add_{p['id']}"))
        if len(row) == 2:
            keyboard.inline_keyboard.append(row)
            row = []
    if row:
        keyboard.inline_keyboard.append(row)

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(call: CallbackQuery):
    product_id = int(call.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO cart (user_id, product_id) VALUES ($1, $2)", call.from_user.id, product_id)
    await call.answer("✅ Savatga qo'shildi! Xaridni yakunlash uchun 'Savatim' bo'limiga o'ting.", show_alert=True)

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
        "💳 <i>To'lov qilish uchun quyidagi kartalardan biriga pul o'tkazing va chekni (rasm ko'rinishida) shu yerga yuboring:</i>\n\n"
        "🟢 <b>Humo:</b> <code>9860 1601 5386 7058</code>\n"
        "🔵 <b>Uzcard:</b> <code>5614 6822 1669 527</code>\n"
        "👤 <b>Jaloliddin Alisherov</b>"
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
        f"💰 <b>Jami:</b> {total:,} so'm"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{user_id}_{total}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{user_id}")]
    ])
    
    await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await message.answer("✅ Chek qabul qilindi. Admin tasdiqlashi bilan xarid amalga oshadi.", reply_markup=get_main_menu())
    await state.clear()

# --- Kabinet, Pul yechish va Hamkorlik ---
@dp.message(F.text == "👤 Kabinet")
async def show_cabinet(message: Message):
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", message.from_user.id)
    text = (
        f"<b>Kabinetingiz</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💰 Balans: <b>{(balance or 0):,} so'm</b>\n\n"
        f"<i>Balansingizdagi mablag'ni karta orqali yechib olishingiz mumkin.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=withdraw_keyboard())

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
        await conn.execute("UPDATE users SET balance = 0 WHERE user_id = $1", user_id)
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    admin_text = (
        f"💸 <b>Pul yechish so'rovi!</b>\n"
        f"👤 Mijoz: {username}\n"
        f"💰 Summa: {balance:,.0f} so'm\n"
        f"💳 Karta: <code>{card_number}</code>"
    )
    
    await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode=ParseMode.HTML)
    await message.answer("✅ So'rov adminga yuborildi. Pul tez orada kartangizga tushirib beriladi.", reply_markup=get_main_menu())
    await state.clear()

@dp.message(F.text == "🤝 Hamkorlik")
async def show_affiliate(message: Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(
        f"<b>1% Cashback Dasturi</b>\n\n"
        f"Do'stlaringizni taklif qiling va ular xarid qilgan summadan <b>1% bonus</b> oling.\n\n"
        f"🔗 Havolangiz:\n<code>{ref_link}</code>", 
        parse_mode=ParseMode.HTML
    )

# ==========================================
# 6. ADMIN PANEL
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👨‍💻 <b>Admin Panel</b>\n\nKerakli bo'limni tanlang:", reply_markup=admin_panel_keyboard(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_broadcast")
async def ask_broadcast_msg(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("📝 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:")
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
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi.")
    await state.clear()

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
# 7. TASDIQLASH (1% Bonus) MANTIQI
# ==========================================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    data = call.data.split("_")
    user_id = int(data[1])
    amount = int(data[2])
    
    await bot.send_message(user_id, "🎉 To'lovingiz tasdiqlandi! Tez orada buyurtmangiz yetkaziladi.")
    
    bonus = int(amount * 0.01) # 1% Cashback hisobi
    async with db_pool.acquire() as conn:
        referrer_id = await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
        if referrer_id:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", bonus, referrer_id)
            await bot.send_message(referrer_id, f"💸 Taklif qilgan do'stingiz xarid qildi! Balansingizga <b>{bonus:,} so'm</b> qo'shildi.", parse_mode=ParseMode.HTML)
        
        await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id)
            
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>TASDIQLANGAN</b>", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id)
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
