<div align="center">

# Mehfil Restaurant Lahore — WhatsApp Bot

**An automated WhatsApp ordering bot** that lets customers browse the menu, place
orders, choose payment (Cash on Delivery / JazzCash), track order status, and much
more — **entirely over WhatsApp**. The bot speaks **English *and* Roman Urdu**,
automatically matching the language the customer writes in.

</div>

## Demo
![Uploading WhatsApp Image 2026-10-08 at 10.00.24 PM.jpeg…]()


---

## Features

- **Full WhatsApp ordering flow** — browse menu → place order → pick payment → track status
- **Bilingual replies** — auto-detects English or Roman Urdu from the customer's message
- **Real WhatsApp number integration** — pairs to a live number via QR/pairing code (Baileys)
- **Smart, typo-tolerant command matching** — e.g. `timing`, `tyming`, `time` all work
- **Multiple payment options** — Cash on Delivery & JazzCash
- **Fuzzy dish detection** — understands `order nihari 2 and lassi 1`
- **Admin dashboard views** — every customer + every order at a glance
- **Persistent database** — SQLite locally, Postgres in production (Docker)
- **Two integration paths**:
 1. Self-hosted Baileys gateway (Node.js)
 2. Meta WhatsApp Cloud API webhook (Graph API)

---

## How It Works (Architecture)

The system is built from **two services** that talk to each other:

```text
 WhatsApp message 
 Customer wa-gateway (Node) 
 WhatsApp Baileys + QR page 
 reply sent back 
 POST /webhook/test
 
 
 Backend (FastAPI) 
 app/main.py 
 - understands msg 
 - CRUD orders/customers 
 
 SQLite / Postgres
 
 
 Restaurant DB 
 (customers/orders) 
 
```

**Flow (Baileys gateway path):**

1. Customer texts the **linked WhatsApp number**.
2. `wa-gateway/bridge.js` receives it and forwards it to the backend
 at `POST http://localhost:8001/webhook/test`.
3. The backend's `generate_reply()` decides the correct bilingual reply and
 saves orders/customers in the database.
4. The gateway relays the reply back to the customer on WhatsApp.

**Alternative — Meta Cloud API:** If you'd rather use Meta's official WhatsApp
Cloud API instead of Baileys, the backend also exposes a webhook at
`POST /webhook` (with verification handshake at `GET /webhook`). Fill in your
Meta credentials in `.env` and point Meta's webhook at your deployed URL.

---

## Project Structure

```text
restaurant-bot/
 app/ # Python backend (the brain)
 main.py # FastAPI — webhook, menu, admin, bot logic
 database.py # SQLAlchemy models + DB setup / migrations
 seed.py # Seed script — fills menu + FAQs (run once)
 __init__.py

 wa-gateway/ # Node.js WhatsApp gateway
 bridge.js # Baileys bridge — links the real WhatsApp number
 package.json
 session/ # WhatsApp login session — NEVER commit

 Dockerfile # Backend image
 docker-compose.yml # Backend + Postgres database
 requirements.txt # Python dependencies
 restaurant.db # Local SQLite database (auto-created)

 .env # Real secrets — DO NOT commit
 .env.example # Template for .env (committed)
 .python-version
 .gitignore
 README.md
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | [FastAPI](https://fastapi.tiangolo.com) + Uvicorn |
| Database ORM | [SQLAlchemy](https://www.sqlalchemy.org) 2.0 |
| Database | SQLite (dev/local) · PostgreSQL (production/Docker) |
| WhatsApp gateway | Node.js + [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) |
| Config / env | python-dotenv |
| HTTP client | httpx / requests |
---

## Prerequisites

- **Python 3.12+**
- **Node.js 18+** (for the WhatsApp gateway)
- **npm** (for gateway dependencies)
- *(Optional)* **Docker + Docker Compose** for production-style deployment

---

## Quick Start (Local)

### 1. Set up the backend

```bash
cd restaurant-bot

# Create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate # Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Create your environment file from the template
cp .env.example .env # then fill in real values (see Configuration below)
```

### 2. Install the WhatsApp gateway

```bash
cd wa-gateway
npm install # installs Baileys + dependencies
cd ..
```

### 3. Seed the database (first time only)

```bash
source .venv/bin/activate
python -m app.seed
```

### 4. Run both services (two terminals)

```bash
# Terminal 1 — Bot API backend (port 8001)
source .venv/bin/activate
uvicorn app.main:app --port 8001

# Terminal 2 — WhatsApp gateway (port 8002)
cd wa-gateway
node bridge.js
```

### 5. Link your WhatsApp number

1. Open **http://localhost:8002** in your browser.
2. A **QR code** (and a pairing code) will appear.
3. On your phone: **WhatsApp → Settings → Linked devices → Link a device** →
 scan the QR or enter the pairing code.
4. Once it says **CONNECTED — you can close this page**, the bot is live.

> Want to test the bot logic *without* a real phone?
> ```bash
> curl -X POST http://localhost:8001/webhook/test \
> -H "Content-Type: application/json" \
> -d '{"sender": "923001234567", "message": "menu"}'
> ```

---

## WhatsApp Commands

The bot understands all of these — in **English or Roman Urdu**:

| Command | What it does |
|------------------------------|------------------------------------------------------------|
| `menu` / `dishes` | Show the full menu, grouped by category |
| `special` / `recommend` | Today's recommended / signature dishes |
| `order nihari 2` | Place an order (dish + quantity, multiple dishes allowed) |
| `timing` / `location` | Restaurant hours & address (typo-tolerant) |
| `payment` / `cash` | Payment options (Cash on Delivery / JazzCash) |
| `status` | Track your recent orders |
| `cancel` | Cancel an order |
| `help` / `commands` | List available commands |
| `hi` / `hello` / `salam` | Greeting + onboarding |
| `thanks` / `bye` | Friendly farewell |

**Order example:**

```text
customer: order nihari 2 aur lassi 1
bot: Thank you! Your order has been noted:
 • Nihari x 2
 • Lassi x 1
 Order ID: #12
 How would you like to pay? (Cash on Delivery / JazzCash)
```

---

## API Endpoints

| Method | Path | Description |
|--------|-----------------------|-------------------------------------------------------|
| GET | `/` | Bot status + endpoint list |
| GET | `/health` | Health check |
| GET | `/menu` | All available menu items (grouped by category) |
| GET | `/recommendations` | Recommended dishes |
| GET | `/faq` | All FAQ entries |
| POST | `/customers` | Create / update a customer |
| POST | `/orders` | Create an order programmatically |
| GET | `/webhook` | Meta webhook verification handshake |
| POST | `/webhook` | Meta WhatsApp Cloud API webhook |
| POST | `/webhook/test` | Local test / simulation webhook (used by the gateway) |
| GET | `/admin/customers` | All customers (name, phone#, address, orders) |
| GET | `/admin/orders` | All orders (items, payment, status, timings) |

### Useful URLs

| URL | What it shows |
|------------------------------------------|------------------------------------------------------|
| `http://localhost:8001` | Bot status + endpoint list |
| `http://localhost:8001/admin/customers` | Every client (name, phone#, address, order count) |
| `http://localhost:8001/admin/orders` | Every order (items, payment, placed/delivery time) |
| `http://localhost:8002` | WhatsApp QR / pairing page |
---

## Configuration (`.env`)

The `.env.example` file lists every variable the project needs. Copy it to
`.env` and fill in real values — **never commit `.env`** (it is already in `.gitignore`).

| Variable | Required | Purpose |
|----------------------------|-----------------------------------|----------|
| `DATABASE_URL` | Always | SQLAlchemy connection string. Local: `sqlite:///./restaurant.db`; Production: `postgresql+psycopg://...` |
| `WHATSAPP_TOKEN` | Only for Meta Cloud API | Meta Graph access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Only for Meta Cloud API | Your business number's ID |
| `WHATSAPP_VERIFY_TOKEN` | Only for Meta Cloud API | Random string to verify the webhook caller |

> If you use the local **Baileys gateway** path, you don't need the `WHATSAPP_*`
> variables at all — the gateway talks to the backend locally.

---

## Database Schema

| Table | Key Columns | Purpose |
|------------------|----------------------------------------------------------------------|----------|
| `customers` | `phone_number` (unique), `name`, `address`, `created_at` | Saved customer profiles |
| `menu_items` | `name`, `category`, `price`, `is_available`, `is_recommended` | The menu |
| `orders` | `customer_id`, `items_json`, `total_price`, `status`, `payment_method`, `placed_at`, `delivered_at` | Every order: placed → confirmed → delivered |
| `faqs` | `question`, `answer` | FAQ knowledge base |

Tables are created automatically the first time the app starts. The seed script
(`python -m app.seed`) fills in starting menu items and FAQs.

### View the local database

```bash
sqlite3 restaurant.db
SELECT * FROM customers;
SELECT * FROM orders;
```

Or graphically with DB Browser: `sudo apt install sqlitebrowser` → open `restaurant.db`.

---

## Docker Deployment (Production)

```bash
cp .env.example .env # fill in real values
docker compose up -d --build
```

What happens:

- **backend** container runs the FastAPI app (port `8000`) and loads `.env`.
- **database** container runs **PostgreSQL 16** with a persistent volume.
- The backend auto-creates its Postgres tables on startup.

> The `wa-gateway` (Node) is currently **not** in the Docker Compose file —
> it runs on the host machine (port `8002`) and must be kept running alongside it.
> To use it against the Docker backend, update `BOT_API` in
> `wa-gateway/bridge.js` to point to the deployed backend URL instead of `localhost:8001`.

---

## Troubleshooting

| Problem | Fix |
|------------------------------------------|-----|
| `connection refused` on port `8001` | Backend not running — start uvicorn first. |
| QR page shows *"No QR yet"* | Ensure `node bridge.js` is running, then refresh. |
| Bot not replying on WhatsApp | Check both services are up — backend **and** gateway. |
| *"Logged out"* in the gateway | Delete `wa-gateway/session/` and re-link (re-scan the QR). |
| Port `8002` already in use | Change `QR_PAGE_PORT` in `bridge.js`. |
| Replies are in the wrong language | The bot mirrors the language of the customer's own message. |

---

## Security Notes

- **Never commit**: `.env`, `restaurant.db`, or `wa-gateway/session/` — they contain
 secrets, customer PII, and WhatsApp login credentials. All three are already
 covered by `.gitignore`.
- If you're pushing to a **public** GitHub repo, run `git status` before committing
 to confirm none of these files sneak in.
- Change `WHATSAPP_VERIFY_TOKEN` to a random value you invent — don't keep the example.

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/awesome`
3. Commit your changes: `git commit -am 'Add awesome feature'`
4. Push to the branch: `git push origin feature/awesome`
5. Open a Pull Request.

---

<p align="center">
<b>Made with for Mehfil Restaurant Lahore</b>
</p>
