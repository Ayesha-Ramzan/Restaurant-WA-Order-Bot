"""
Main FastAPI backend - the "brain" of the restaurant WhatsApp bot.

WHY this structure:
Hermes Agent will call this API's /webhook endpoint whenever a customer
sends a WhatsApp message. This file decides what the bot replies.
"""

import json
import os
import re
import requests
from fastapi import FastAPI, Depends, Request, Query
from sqlalchemy.orm import Session

from app.database import init_db, get_db, Customer, MenuItem, Order, FAQ

from contextlib import asynccontextmanager

# WHY: loads .env file so WHATSAPP_TOKEN etc. become environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # WHY: makes sure database tables exist before the app starts serving requests
    init_db()
    yield

app = FastAPI(title="Restaurant WhatsApp Bot", lifespan=lifespan)


@app.get("/")
def home():
    # WHY: opening http://localhost:8001 in a browser shows a friendly page
    # instead of {"detail":"Not Found"} which looks like nothing is running.
    return {
        "restaurant": "Mehfil Restaurant Lahore",
        "status": "running ✅",
        "whatsapp_gateway_page": "http://localhost:8002",
        "endpoints": {
            "health": "/health",
            "menu": "/menu",
            "simulate_whatsapp_message": "POST /webhook/test",
            "real_whatsapp_webhook": "/webhook",
        },
    }


@app.get("/health")
def health_check():
    # WHY: quick way to confirm the bot is alive before a demo/interview
    return {"status": "running", "message": "Bot is alive ✅"}


@app.get("/menu")
def get_menu(db: Session = Depends(get_db)):
    """Return all available menu items, grouped by category."""
    items = db.query(MenuItem).filter(MenuItem.is_available == True).all()
    return [
        {"name": i.name, "category": i.category, "price": i.price, "recommended": i.is_recommended}
        for i in items
    ]


@app.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    """Return the restaurant's favourite/recommended dishes."""
    items = db.query(MenuItem).filter(MenuItem.is_recommended == True, MenuItem.is_available == True).all()
    return [{"name": i.name, "price": i.price} for i in items]


@app.get("/faq")
def get_all_faq(db: Session = Depends(get_db)):
    faqs = db.query(FAQ).all()
    return [{"question": f.question, "answer": f.answer} for f in faqs]


@app.post("/customers")
def save_customer(phone_number: str, name: str = None, address: str = None, db: Session = Depends(get_db)):
    """Create or update a customer's saved details (name/address)."""
    customer = db.query(Customer).filter(Customer.phone_number == phone_number).first()
    if customer is None:
        customer = Customer(phone_number=phone_number, name=name, address=address)
        db.add(customer)
    else:
        if name:
            customer.name = name
        if address:
            customer.address = address
    db.commit()
    db.refresh(customer)
    return {"id": customer.id, "phone_number": customer.phone_number, "name": customer.name, "address": customer.address}


@app.post("/orders")
def create_order(phone_number: str, items: list[dict], db: Session = Depends(get_db)):
    """
    Create a new order for a customer.
    items example: [{"name": "Chicken Biryani", "qty": 2, "price": 450}]
    """
    customer = db.query(Customer).filter(Customer.phone_number == phone_number).first()
    if customer is None:
        customer = Customer(phone_number=phone_number)
        db.add(customer)
        db.commit()
        db.refresh(customer)

    total = sum(item["qty"] * item["price"] for item in items)
    order = Order(customer_id=customer.id, items_json=json.dumps(items), total_price=total, status="pending")
    db.add(order)
    db.commit()
    db.refresh(order)

    return {"order_id": order.id, "total_price": total, "status": order.status}


@app.get("/webhook")
def whatsapp_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta requires a GET verification handshake when you first register the webhook URL.
    We echo back hub.challenge if the verify token matches WHATSAPP_VERIFY_TOKEN in .env.
    """
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_secret_token_123")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return int(hub_challenge)  # Meta expects the raw challenge number back
    return {"error": "verification failed"}


@app.post("/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Real WhatsApp Cloud API webhook:
    Meta POSTs every incoming WhatsApp message here in their own JSON format.
    We parse it, decide the reply with the same bot logic, and SEND the reply
    back to the customer via the Graph API.
    """
    payload = await request.json()

    # Meta's payload shape: entry[].changes[].value.messages[]
    try:
        change = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}

    # Status updates (delivered/read receipts) have no messages - skip them
    if "messages" not in change:
        return {"status": "ignored"}

    message = change["messages"][0]
    sender_phone = message.get("from")           # customer's phone number
    msg_type = message.get("type", "text")

    # Only handle text messages for now (images/stickers get a friendly fallback)
    if msg_type == "text":
        message_text = message["text"]["body"].strip().lower()
    elif msg_type == "interactive":  # button / list replies
        interactive = message.get("interactive", {})
        message_text = interactive.get("button_reply", {}).get("title", "") or \
                       interactive.get("list_reply", {}).get("title", "")
        message_text = message_text.strip().lower()
    else:
        message_text = ""

    reply_text = generate_reply(message_text, sender_phone, db)
    send_whatsapp_message(sender_phone, reply_text)
    return {"status": "replied"}


def send_whatsapp_message(to_phone: str, text: str):
    """
    Sends a WhatsApp text message back to the customer using the Meta Cloud API.
    Reads credentials from the .env file:
      WHATSAPP_TOKEN            - permanent/temporary access token from Meta
      WHATSAPP_PHONE_NUMBER_ID  - your business phone number's ID
    If credentials are missing, it just logs the message instead (so local
    testing never crashes).
    """
    token = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    if not token or not phone_id or token.startswith("your_"):
        print(f"[BOT - no credentials, not sent] -> {to_phone}: {text}")
        return

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        if resp.status_code != 200:
            print(f"[BOT] Failed to send message: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        print(f"[BOT] Error sending message: {e}")



# ============================================================================
# MEHFIL RESTAURANT LAHORE - BOT BRAIN
# ============================================================================

BOT_NAME = "Mehfil Restaurant Lahore"

# Full menu. Prices are None because the printed menu shows "PKR —"
# (add real prices later by putting e.g. 850 instead of None).
MENU = {
    "Starters - to begin, at the table": [
        ("Kata Kat, Table-Side", "Minced offal and spice cut on the tawa; trotters and brain from Bakar Mandi."),
        ("Dahi Bhalla, Deconstructed", "Lentil dumplings, set yoghurt, tamarind reduction, pomegranate."),
        ("Seekh, Charcoal & Coriander", "Hand-pounded beef seekh on green chilli and coriander stalk."),
        ("Bihari Boti Tartlet", "Twelve-hour papaya-tenderised beef in a crisp shell."),
        ("Fried Fish, Ravi Style", "Rohu in ajwain batter, chaat masala, lime."),
    ],
    "Grill & Charcoal - mango wood, clay, open flame": [
        ("The Champ", "Mutton chops in raw papaya and white pepper, over mango wood."),
        ("Chargha, Whole Bird", "Steamed a full day in spice, fried to lacquer. Serves two."),
        ("Malai Boti, Kashmiri Chilli", "Chicken thigh set in cream and cheese overnight."),
        ("Tandoori Quail", "Four birds, yoghurt marinade, burnt lemon."),
        ("Reshmi Kebab, Almond", "Silk-textured chicken kebab bound with almond paste."),
    ],
    "Rice & Biryani - sealed, layered, opened at your table": [
        ("Lahori Biryani, Sealed", "Clay pot, dough-sealed, opened at your table. Aged sella rice."),
        ("Mutton Yakhni Pulao", "Rice cooked in the meat's own broth; no shortcuts."),
        ("Prawn Biryani, Coastal Line", "Karachi prawns, the Lahori masala."),
        ("Zarda Pulao Bahar", "Saffron sweet rice with khoya, pistachio, candied orange."),
    ],
    "Curries - the long fires": [
        ("Nihari, Eight Hours", "Shank simmered overnight, marrow served in the bone."),
        ("Paya, Clarified", "Trotters reduced to a clear, gelatinous broth."),
        ("Haleem, Stone-Ground", "Seven grains and beef pounded to silk over nine hours."),
        ("Palak Paneer, House Cheese", "Spinach cooked twice, cheese set that morning."),
        ("Daal Maash, Butter-Finished", "White lentils, ginger julienne, burnt-butter tarka."),
    ],
    "Street, Reimagined - Anarkali and Gawalmandi, plated": [
        ("Anarkali Gol Gappa Flight", "Six shells, six waters, served on a chilled slate."),
        ("Fruit Chaat, Winter Cut", "The mandi's best this morning, black salt, orange juice."),
    ],
    "Desserts - milk, reduced and reduced again": [
        ("Kulfi Falooda, Tall Glass", "Slow-churned khoya kulfi, rose vermicelli, basil seed."),
        ("Shahi Tukray", "Ghee-fried bread in cardamom rabri, silver leaf."),
        ("Gajar Halwa, Winter Only", "Red carrots reduced in milk for five hours. From Kasur."),
        ("Rabri Set, Pistachio", "Milk reduced to ribbons, chilled overnight."),
    ],
    "Drinks - clay, ice, forty minutes of whisking": [
        ("Kashmiri Chai, Pink Salt", "Whisked forty minutes to colour."),
        ("Doodh Soda, House", "Cold milk and soda, the old Lahori order."),
        ("Lassi, Sweet or Salted", "Clay tumbler, churned to order."),
        ("Sardai", "Almond, melon seed, fennel, cooled on ice."),
        ("Sikanjabeen", "Mint, lime, black salt."),
    ],
}

# Flat lookup: lowercase dish name -> (display name, price)
DISH_LOOKUP = {}
for _cat, _dishes in MENU.items():
    for _name, _desc in _dishes:
        DISH_LOOKUP[_name.lower()] = (_name, None)

# WHY: in-memory conversation state per customer (after items are chosen
# we ask: Cash on Delivery or JazzCash)
ORDER_STATE = {}
LANG_STATE = {}  # WHY: remembers each customer's language so short replies ("jazzcash", "menu") stay in the same language

def is_urdu(message_text: str) -> bool:
    """Detect Roman Urdu vs English. Urdu words -> Roman Urdu reply, else English."""
    urdu_words = (
        "aap", "ap", "kya", "kia", "kaise", "kaisay", "kese", "hai", "hain", "ho",
        "chahiye", "chahiya", "chahta", "chahti", "karna", "karni", "krna", "likh",
        "bata", "batao", "mera", "meri", "kitna", "kitne", "kab", "nahi", "nahin",
        "shukriya", "jazakallah", "bhai", "khana", "milega", "dena", "pata", "mujhe",
        "mujhay", "hum", "ham", "acha", "theek", "karo", "kardein", "dedo", "lena",
        "chal", "abhi", "kitni", "bhej", "bhejo", "yeh", "ye ", "woh", "rubaru",
    )
    words = message_text.split()
    return any(w in urdu_words for w in words)

POLICY_REPLY = {
    "ur": (
        "Maazrat chahta hoon, ye baat humari policy ke mutabiq nahi. \n"
        "Hum sirf food orders aur restaurant ki maloomat mein madad kar sakte hain.\n\n"
        "Meherbani kar ke order dein — *menu* likhein. "
    ),
    "en": (
        "Apologies, but that's against our policy. \n"
        "We can only assist with food orders and restaurant information.\n\n"
        "Kindly place your order — type *menu* to see our dishes. "
    ),
}

PAYMENT_PROMPT = {
    "ur": (
        "💳 *Payment kaise karenge aap?*\n\n"
        "1️⃣ *Cash on Delivery*\n"
        "2️⃣ *JazzCash*\n\n"
        "*cash* ya *jazzcash* likh dein. "
    ),
    "en": (
        "💳 *How would you like to pay?*\n\n"
        "1️⃣ *Cash on Delivery*\n"
        "2️⃣ *JazzCash*\n\n"
        "Please reply with *cash* or *jazzcash*. "
    ),
}


def _find_dishes_in_text(message_text: str):
    """Finds every dish from the menu mentioned in the message text."""
    found = []
    for key, (display_name, price) in DISH_LOOKUP.items():
        short = key.split(",")[0]
        if short in message_text:
            found.append((display_name, price))
    return found


def generate_reply(message_text: str, sender_phone: str, db: Session) -> str:
    """
    The bot's brain. Replies in the same language the customer uses:
    Roman Urdu -> Roman Urdu, English -> English.
    """
    message_text = message_text.strip().lower()
    detected = "ur" if is_urdu(message_text) else "en"
    # WHY: short command-only replies ("jazzcash", "menu", "cash") carry no
    # language signal - continue in the language of the conversation so far.
    # Signal words are checked as whole words to avoid false matches
    # (e.g. "i " inside "nihari").
    _signal = ("aap", "kya", "chahiye", "hai", "hain", "mujhe", "mera", "meri",
               "please", "you", "your", "me", "i", "want", "like")
    _has_signal = any(w in message_text.split() for w in _signal)
    L = detected if _has_signal else LANG_STATE.get(sender_phone, detected)
    LANG_STATE[sender_phone] = L

    # ---------------------------------------------------------------
    # STEP 3: customer sends name & address for delivery
    # ---------------------------------------------------------------
    state = ORDER_STATE.get(sender_phone)
    if state and state.get("awaiting_address"):
        if "cancel" in message_text:
            ORDER_STATE.pop(sender_phone, None)
            return (
                "Ji bilkul, aap ka order cancel kar diya hai.  Jab dil kare, *menu* likh kar dobara order kar lein. "
                if L == "ur" else
                "Your order has been cancelled.  Type *menu* whenever you'd like to order again."
            )
        if len(message_text) < 5:
            return (
                "Apna *poora naam* aur *mukammal pata* ek message mein bhej dein, misal:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*\n\n"
                "Cancel karna ho to *cancel* likhein."""
                if L == "ur" else
                "Please send your *full name* and *complete delivery address* in one message, for example:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*\n\n"
                "Or type *cancel* to cancel the order."
            )
        customer = db.query(Customer).filter(Customer.phone_number == sender_phone).first()
        if customer:
            parts = message_text.split(",", 1)
            customer.name = parts[0].strip().title()
            customer.address = (parts[1].strip().title() if len(parts) > 1 else message_text.title())
            db.commit()

        # WHY: record WHEN the order was confirmed and WHEN it should be delivered
        from datetime import datetime, timedelta
        now = datetime.now()
        eta = now + timedelta(minutes=45)
        order_row = db.query(Order).filter(Order.id == state["order_id"]).first()
        if order_row:
            order_row.placed_at = now
            order_row.delivered_at = eta
            order_row.status = "confirmed"
            order_row.payment_method = state.get("payment", "cash")
            db.commit()

        ORDER_STATE.pop(sender_phone, None)
        items_lines = "\n".join(f"• {i['name']} x {i['qty']}" for i in state["items"])
        pay_label = "JazzCash" if state.get("payment") == "jazzcash" else "Cash on Delivery"
        time_str = now.strftime("%d %b %Y, %I:%M %p")
        eta_str = eta.strftime("%I:%M %p")
        if L == "ur":
            return (
                "✅ *ORDER CONFIRM - SHUKRIYA!* 🍽\n\n"
                f"🥣 *Mehfil Restaurant Lahore*\n"
                f"Order ID: #{state['order_id']}\n\n"
                f"{items_lines}\n\n"
                f"💵 Payment: *{pay_label}*\n"
                f"🕒 Order time: {time_str}\n"
                f"🛬 Delivery *{eta_str} tak* (30-45 minute)\n\n"
                "📞 Confirm ke liye aap ko call aa jayegi.\n"
                "Mehfil par order karne ka shukriya! "
            )
        return (
            "✅ *ORDER CONFIRMED - THANK YOU!* 🍽\n\n"
            f"🥣 *Mehfil Restaurant Lahore*\n"
            f"Order ID: #{state['order_id']}\n\n"
            f"{items_lines}\n\n"
            f"💵 Payment: *{pay_label}*\n"
            f"🕒 Order placed at: {time_str}\n"
            f"🛬 Expected delivery by *{eta_str}* (30-45 minutes)\n\n"
            "📞 You will receive a confirmation call shortly.\n"
            "Thank you for ordering from Mehfil! "
        )

    # ---------------------------------------------------------------
    # STEP 2: payment method
    # ---------------------------------------------------------------
    if state and state.get("awaiting_payment"):
        items_lines = "\n".join(f"• {i['name']} x {i['qty']}" for i in state["items"])
        if "cancel" in message_text:
            ORDER_STATE.pop(sender_phone, None)
            return (
                "Ji bilkul, aap ka order cancel kar diya hai.  Jab dil kare, *menu* likh kar dobara order kar lein. 😊"
                if L == "ur" else
                "Your order has been cancelled.  Type *menu* whenever you'd like to order again. 😊"
            )
        if "jazz" in message_text:
            ORDER_STATE[sender_phone] = {
                "items": state["items"], "order_id": state["order_id"],
                "payment": "jazzcash", "awaiting_address": True,
            }
            return (
                "💳 Bohat achha! *JazzCash* theek hai.\nPayment ka number aap ko jald bhej dein ge.\n\n"
                "📢 Ab order pohnchane ke liye apna *poora naam* aur *mukammal pata* ek message mein bhej dein, misal:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*"
                if L == "ur" else
                "💳 Great choice — *JazzCash* it is.\nWe'll share the JazzCash payment number with you shortly.\n\n"
                "📢 To deliver your order, please send your *full name* and *complete delivery address* in one message, for example:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*"
            )
        if "cash" in message_text or "cod" in message_text:
            ORDER_STATE[sender_phone] = {
                "items": state["items"], "order_id": state["order_id"],
                "payment": "cash", "awaiting_address": True,
            }
            return (
                "💵 Ji bilkul! *Cash on Delivery* theek hai — kharcha delivery par ada karein.\n\n"
                "📢 Apna *poora naam* aur *mukammal pata* ek message mein bhej dein, misal:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*"
                if L == "ur" else
                "💵 Perfect — *Cash on Delivery* it is.\n\n"
                "📢 To deliver your order, please send your *full name* and *complete delivery address* in one message, for example:\n"
                "*Ali Khan, House 12, Street 5, DHA Phase 4, Lahore*"
            )
        return (
            "Payment kaise karenge aap? *cash* ya *jazzcash* likh dein. \n"
             "Cancel karna ho to *cancel* likhein."
            if L == "ur" else
            "Please choose a payment method: reply *cash* for Cash on Delivery or *jazzcash* for JazzCash. 😊\n"
            "Or type *cancel* to cancel the order."
        )

    # ---------------------------------------------------------------
    # Cancel
    # ---------------------------------------------------------------
    if "cancel" in message_text:
        if sender_phone in ORDER_STATE:
            ORDER_STATE.pop(sender_phone, None)
            return (
                "Ji order cancel ho gaya. 🙏 Naya order karne ke liye *menu* likhein."
                if L == "ur" else
                "Your order has been cancelled. 🙏 Type *menu* to start a new order."
            )
        return (
            "Confirm order cancel karne ke liye humein call karein ya Order ID ke saath *cancel* likhein. *menu* likh kar dishes dekh sakte hain. "
            if L == "ur" else
            "To cancel a confirmed order, please call us or send your Order ID with the word cancel. Type *menu* to browse our dishes. "
        )

    # ---------------------------------------------------------------
    # Order status / tracking
    # ---------------------------------------------------------------
    if any(w in message_text for w in ["status", "my order", "track", "kahan", "mera order"]):
        customer = db.query(Customer).filter(Customer.phone_number == sender_phone).first()
        orders = (
            db.query(Order).filter(Order.customer_id == customer.id)
            .order_by(Order.id.desc()).limit(3).all()
            if customer else []
        )
        if not orders:
            return (
                "Abhi tak koi order nahi aaya aap ka. *menu* likhein aur mazedaar dishes dekhein! 🍛"
                if L == "ur" else
                "You have no orders yet. Type *menu* to see our delicious dishes! 🍛"
            )
        lines = ["📦 *YOUR RECENT ORDERS*\n"] if L == "en" else ["📦 *AAP KE HALIYA ORDERS*\n"]
        for o in orders:
            lines.append(f"• Order #{o.id} - {o.status} - Rs.{o.total_price}")
        lines.append(
            "\nNaya order karne ke liye *menu* likhein. " if L == "ur"
            else "\nType *menu* to place a new order. "
        )
        return "\n".join(lines)

    # ---------------------------------------------------------------
    # Help / commands
    # ---------------------------------------------------------------
    if any(w in message_text for w in ["help", "commands", "options", "madad"]):
        if L == "ur":
            return (
                "🔤 *MEHFIL RESTAURANT LAHORE - RABTA*\n\n"
                "• *menu* - poori dishes list\n"
                "• *special* - aaj ke recommended dishes\n"
                "• *order <dish> <qty>* - order ke liye, misal *order nihari 2*\n"
                "• *timing* ya *location* - restaurant info\n"
                "• *status* - apne orders dekhein\n"
                "• *cancel* - order cancel karein\n\n"
                "💵 Hum *Cash on Delivery* aur *JazzCash* qabool karte hain."
            )
        return (
            "🔤 *MEHFIL RESTAURANT LAHORE*\n\n"
            "• *menu* - full dishes list\n"
            "• *special* - today's recommended dishes\n"
            "• *order <dish> <qty>* - place an order, e.g. *order nihari 2*\n"
            "• *timing* or *location* - restaurant info\n"
            "• *status* - track your orders\n"
            "• *cancel* - cancel your order\n\n"
            "💵 We accept *Cash on Delivery* and *JazzCash*."
        )

    # ---------------------------------------------------------------
    # Greeting & Welcome
    # ---------------------------------------------------------------
    if re.search(r"\b(hi|hello|hey|start|salam|assalam|asalam|aoa)\b", message_text):
        if L == "ur":
            return (
                "*Assalam-o-Alaikum!* 👋\n\n"
                f"*{BOT_NAME}* mein khush-amdeed! 🍛\n"
                "Main aap ki khidmat mein hazir hoon. \n\n"
                "1️⃣ *menu* likhein — poori dishes list ke liye\n"
                "2️⃣ *special* likhein — aaj ke recommended dishes\n"
                "3️⃣ *order nihari 2* — order karne ke liye\n"
                "4️⃣ *timing* ya *location* — restaurant info\n\n"
                "💵 Hum *Cash on Delivery* aur *JazzCash* qabool karte hain.\n\n"
                "Aaj aap ka kya order hoga? "
            )
        return (
            "*Assalam-o-Alaikum!* 👋\n\n"
            f"Welcome to *{BOT_NAME}!* 🍛\n"
            "How may I assist you today? \n\n"
            "1️⃣ *menu* — see our full dishes list\n"
            "2️⃣ *special* — today's recommended dishes\n"
            "3️⃣ *order nihari 2* — place an order\n"
            "4️⃣ *timing* or *location* — restaurant info\n\n"
            "💵 We accept *Cash on Delivery* and *JazzCash*.\n\n"
            "What would you like to order today? "
        )

    # ---------------------------------------------------------------
    # Specials
    # ---------------------------------------------------------------
    elif any(w in message_text for w in ["special", "recommend", "best", "signature", "famous", "popular"]):
        if L == "ur":
            return (
                "⭐ *AAJ KE KHASS DISHES - MEHFIL* ⭐\n\n"
                "🔥 *Nihari, Eight Hours* - subah ki pehli qatli\n"
                "🔥 *The Champ* - mango wood par mutton chops\n"
                "🔥 *Lahori Biryani, Sealed* - aap ke table par khulti hai\n"
                "🔥 *Chargha, Whole Bird* - do shakhs ke liye\n"
                "🔥 *Kulfi Falooda, Tall Glass* - aakhir mein meetha\n\n"
                "💵 Payment: *Cash on Delivery* ya *JazzCash*\n"
                "Order ke liye likhein: *order nihari 2* "
            )
        return (
            "⭐ *TODAY'S SPECIALS AT MEHFIL* ⭐\n\n"
            "🔥 *Nihari, Eight Hours* - the long-fire classic\n"
            "🔥 *The Champ* - mutton chops over mango wood\n"
            "🔥 *Lahori Biryani, Sealed* - opened at your table\n"
            "🔥 *Chargha, Whole Bird* - serves two\n"
            "🔥 *Kulfi Falooda, Tall Glass* - to finish\n\n"
            "💵 Payment: *Cash on Delivery* or *JazzCash*\n"
            "To order, type e.g. *order nihari 2* "
        )

    # ---------------------------------------------------------------
    # Menu
    # ---------------------------------------------------------------
    elif "menu" in message_text or "dish" in message_text:
        lines = [
            f"📋 *{BOT_NAME.upper()} - MENU*\n"
            if L == "en" else
            f"📋 *{BOT_NAME.upper()} - MENU*\n"
        ]
        for category, dishes in MENU.items():
            lines.append(f"\n*🍛 {category}*")
            for name, desc in dishes:
                lines.append(f"• *{name}* - PKR —")
        lines.append(
            "\n💵 Payment: *Cash on Delivery* ya *JazzCash*\nOrder ke liye likhein, misal: *order nihari 2* 😊"
            if L == "ur" else
            "\n💵 Payment: *Cash on Delivery* or *JazzCash*\nTo order, type e.g. *order nihari 2* 😊"
        )
        return "\n".join(lines)

    # ---------------------------------------------------------------
    # FAQs - timing / location (typo tolerant)
    # ---------------------------------------------------------------
    elif any(w in message_text for w in ["timing", "tyming", "timming", "time", "location", "loction",
                                         "locaton", "address", "where", "hours", "open", "close"]):
        if L == "ur":
            return (
                "ℹ️ *MEHFIL RESTAURANT LAHORE*\n\n"
                "📍 Lahore (Main Commercial Area) mein waqe hai\n"
                "🕐 Rozana 12 PM - 12 AM khula\n"
                "🛵 Delivery available hai\n\n"
                "💵 Hum *Cash on Delivery* aur *JazzCash* qabool karte hain.\n\n"
                "*menu* likhein aur dishes dekhein. "
            )
        return (
            "ℹ️ *MEHFIL RESTAURANT LAHORE*\n\n"
            "📍 Located in Lahore (Main Commercial Area)\n"
            "🕐 Open every day, 12 PM - 12 AM\n"
            "🛵 Delivery available\n\n"
            "💵 We accept *Cash on Delivery* and *JazzCash*.\n\n"
            "Type *menu* to see our dishes. "
        )
    elif any(w in message_text for w in ["payment", "pay", "jazzcash", "cash"]):
        return (
            "💵 *Hum qabool karte hain:*\n\n"
            "1️⃣ *Cash on Delivery* - khana pohnchne par ada karein\n"
            "2️⃣ *JazzCash* - order par payment number share kar dein ge\n\n"
            "*menu* likhein aur order dein."
            if L == "ur" else
            "💵 *We accept:*\n\n"
            "1️⃣ *Cash on Delivery* - pay when your food arrives\n"
            "2️⃣ *JazzCash* - we share the payment number when you order\n\n"
            "Type *menu* and place your order. "
        )

    # ---------------------------------------------------------------
    # Ordering
    # ---------------------------------------------------------------
    elif any(w in message_text for w in ["order", "khana", "place", "chahiye", "likh", "bhej"]):
        dishes = _find_dishes_in_text(message_text)

        if not dishes:
            return (
                "Zaroor! Batayein, kaunsi dishes aur kitni? 😊\n"
                "Aise likhein: *order nihari 2 aur lassi 1*\n\n"
                "Poori list ke liye *menu* likhein. 🍛"
                if L == "ur" else
                "Wonderful! What would you like to have? 😊\n"
                "Just tell me the *dishes and quantity*, for example:\n"
                "*order nihari 2 and lassi 1*\n\n"
                "Type *menu* to see all our dishes. 🍛"
            )

        items = [{"name": name, "qty": 1, "price": price} for name, price in dishes]
        qty_match = re.search(r"\b(\d{1,3})\b", message_text)
        qty = max(1, int(qty_match.group(1))) if qty_match else 1
        for item in items:
            item["qty"] = qty

        customer = db.query(Customer).filter(Customer.phone_number == sender_phone).first()
        if not customer:
            customer = Customer(phone_number=sender_phone)
            db.add(customer)
            db.commit()
            db.refresh(customer)

        total = sum((i["price"] or 0) * i["qty"] for i in items)
        new_order = Order(
            customer_id=customer.id,
            items_json=json.dumps(items),
            total_price=total,
            status="pending",
        )
        db.add(new_order)
        db.commit()
        db.refresh(new_order)

        ORDER_STATE[sender_phone] = {"items": items, "order_id": new_order.id, "awaiting_payment": True}

        items_lines = "\n".join(f"• {i['name']} x {i['qty']}" for i in items)
        head = (
            "Bohat shukriya! 🙏 Aap ka order note kar liya hai:"
            if L == "ur" else
            "Thank you! 🙏 Your order has been noted:"
        )
        return (
            f"{head}\n\n{items_lines}\n\n"
            f"Order ID: #{new_order.id}\n\n" + PAYMENT_PROMPT[L]
        )

    # ---------------------------------------------------------------
    # Thanks / goodbye
    # ---------------------------------------------------------------
    elif any(w in message_text for w in ["thank", "shukriya", "bye", "khuda hafiz", "great", "nice"]):
        return (
            "JazakAllah, meharbani!  Dobara order karne ke liye *menu* likhein. 🍛\n"
            "*Mehfil Restaurant Lahore* hamesha aap ki khidmat ke liye hazir hai."
            if L == "ur" else
            "It was a pleasure serving you!  Type *menu* anytime to order again. 🍛\n"
            "*Mehfil Restaurant Lahore* is always at your service."
        )

    # ---------------------------------------------------------------
    # Off-topic / awkward -> policy
    # ---------------------------------------------------------------
    elif any(
        w in message_text
        for w in ["love", "marry", "girlfriend", "boyfriend", "joke", "politics",
                  "religion", "who are you", "your name", "age", "single",
                  "shaadi", "flirt", "free", "bored", "pyar", "piyar", "pasand", "iqras"]
    ):
        return POLICY_REPLY[L]

    # ---------------------------------------------------------------
    # Unknown -> back to food politely
    # ---------------------------------------------------------------
    return (
        "Maaf kijiye, samajh nahi aaya. 🙏\n"
        "Main food order aur restaurant ki maloomat mein hi madad kar sakta hoon.\n\n"
        "*menu* likhein dishes dekhne ke liye, ya *order nihari 2* likh kar order dein. "
        if L == "ur" else
        "Apologies, I didn't quite get that. 🙏\n"
        "I can only help with *food orders* and *restaurant information*.\n\n"
        "Type *menu* to see our dishes, or *order nihari 2* to place an order. "
    )


@app.get("/admin/customers")
def admin_customers(db: Session = Depends(get_db)):
    """
    WHY: lets the owner see every client saved in the database:
    name, phone number and address. Open http://localhost:8001/admin/customers
    """
    customers = db.query(Customer).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "phone_number": c.phone_number,
            "address": c.address,
            "registered_since": c.created_at.strftime("%d %b %Y") if c.created_at else None,
            "total_orders": db.query(Order).filter(Order.customer_id == c.id).count(),
        }
        for c in customers
    ]


@app.get("/admin/orders")
def admin_orders(db: Session = Depends(get_db)):
    """
    WHY: lets the owner see every order with customer details and timings:
    when it was placed and when it will be delivered.
    Open http://localhost:8001/admin/orders
    """
    orders = db.query(Order).order_by(Order.id.desc()).all()
    result = []
    for o in orders:
        cust = db.query(Customer).filter(Customer.id == o.customer_id).first()
        result.append(
            {
                "order_id": o.id,
                "customer_name": cust.name if cust else None,
                "phone_number": cust.phone_number if cust else None,
                "address": cust.address if cust else None,
                "items": json.loads(o.items_json),
                "total_price": o.total_price,
                "payment": (o.payment_method or "cash").upper() if o.status == "confirmed" else "not chosen yet",
                "status": o.status,
                "order_placed_time": o.placed_at.strftime("%d %b %Y, %I:%M %p") if o.placed_at else None,
                "delivery_time": o.delivered_at.strftime("%d %b %Y, %I:%M %p") if o.delivered_at else None,
            }
        )
    return result


@app.post("/webhook/test")
def test_webhook(payload: dict, db: Session = Depends(get_db)):
    """
    Simulates a WhatsApp message locally without needing a real phone.
    Send:  {"sender": "923001234567", "message": "menu"}
    Returns the exact reply that would be sent on WhatsApp.
    """
    message_text = payload.get("message", "")
    sender_phone = payload.get("sender", "unknown")
    reply_text = generate_reply(message_text, sender_phone, db)
    return {"reply": reply_text}
