/**
 * Baileys WhatsApp Gateway
 * ------------------------
 * Connects a REAL WhatsApp number to the restaurant bot.
 *
 * How it works:
 *   1. Logs in once (pairing code or QR) and saves the session in ./session
 *      -> after the first link, it reconnects automatically forever.
 *   2. Every incoming WhatsApp message is forwarded to the bot:
 *      POST http://localhost:8001/webhook/test  { "sender": ..., "message": ... }
 *   3. The bot's reply is sent back to the customer on WhatsApp.
 */

const makeWASocket = require("@whiskeysockets/baileys").default;
const {
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} = require("@whiskeysockets/baileys");
const pino = require("pino");
const BOT_API = "http://localhost:8001/webhook/test";
const QR_PAGE_PORT = 8002;
const MY_NUMBER = "923244060602";

let latestQR = null;
let qrDataURL = null;
let connectionStatus = "starting...";
let latestPairingCode = null;
let isConnected = false;

const http = require("http");
const fs = require("fs");
const path = require("path");
const qrcodeLib = require("qrcode");
const { exec } = require("child_process");

function renderPage() {
  const qrImg = qrDataURL
    ? "<img src='" + qrDataURL + "' width='360' height='360' style='background:#fff;padding:15px;border-radius:12px'>"
    : "<p style='color:#777'>No QR yet — waiting for WhatsApp gateway to emit one...</p>";

  const connectedBanner = isConnected
    ? "<div style='background:#d4edda;color:#155724;padding:12px;border-radius:8px;margin:15px auto;max-width:520px'>"
      + "✅ <strong>Already connected to WhatsApp.</strong> The bot is live and replying to messages.<br>"
      + "You don't need to scan anything. If you want to re-link this number, click the button below."
      + "</div>"
    : "";

  const reLinkButton =
    "<form method='POST' action='/relink' onsubmit='return confirm(\"This will unlink the current WhatsApp number and show a fresh QR. Continue?\")'>"
    + "<button type='submit' style='margin-top:15px;padding:10px 20px;background:#dc3545;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px'>"
    + "🔄 Force new QR (unlink & re-link)"
    + "</button></form>";

  return (
    "<!doctype html><html><head><meta charset='utf-8'>"
    + "<meta http-equiv='refresh' content='3'>"
    + "<title>Mehfil Restaurant Bot — WhatsApp QR</title>"
    + "<style>"
    + "body{background:#f5f5f5;color:#222;font-family:system-ui,sans-serif;text-align:center;padding:30px;margin:0}"
    + "h1,h2,h3,h4{color:#222;margin:6px 0}"
    + ".card{background:#fff;max-width:560px;margin:0 auto;padding:24px;border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,.08)}"
    + ".pairing{background:#fff3cd;color:#856404;padding:8px 12px;border-radius:6px;display:inline-block;font-family:monospace;font-size:18px;letter-spacing:2px;margin:6px 0}"
    + ".steps{text-align:left;max-width:460px;margin:18px auto;line-height:1.6}"
    + "</style></head><body><div class='card'>"
    + "<h1>🍽️ Mehfil Restaurant Bot</h1>"
    + "<h2>Status: " + connectionStatus + "</h2>"
    + connectedBanner
    + "<p><strong>Pairing code:</strong> <span class='pairing'>"
    + (latestPairingCode || "— will appear here —") + "</span></p>"
    + "<h3>Scan this QR code:</h3>"
    + qrImg
    + "<div class='steps'>"
    + "<h4>How to connect WhatsApp:</h4>"
    + "<p><b>Step 1:</b> Open WhatsApp on your phone (0324-4060602)</p>"
    + "<p><b>Step 2:</b> Tap <i>Settings → Linked devices</i></p>"
    + "<p><b>Step 3:</b> Tap <i>Link a device</i> and scan the QR above "
    + "<i>or</i> tap <i>Link with phone number instead</i> and type the pairing code.</p>"
    + "</div>"
    + reLinkButton
    + "<p style='margin-top:18px;color:#888;font-size:12px'>This page auto-refreshes every 3 seconds.</p>"
    + "</div></body></html>"
  );
}

const server = http.createServer(async (req, res) => {
  // Handle the "force re-link" button
  if (req.method === "POST" && req.url === "/relink") {
    try {
      const sessionDir = path.join(__dirname, "session");
      const credsFile = path.join(sessionDir, "creds.json");
      if (fs.existsSync(credsFile)) fs.unlinkSync(credsFile);
      connectionStatus = "session cleared — restarting gateway...";
      isConnected = false;
      latestQR = null;
      qrDataURL = null;
      latestPairingCode = null;
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(
        "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
        + "<h2>✅ Session cleared.</h2>"
        + "<p>Restarting the gateway... this page will refresh automatically.</p>"
        + "<meta http-equiv='refresh' content='3'>"
        + "</body></html>"
      );
      // Restart the whole bridge so Baileys picks up the empty session and emits a fresh QR
      setTimeout(() => {
        process.exit(0); // nodemon / launcher (if any) will respawn; if not, user just runs `npm start` once
      }, 500);
    } catch (e) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end("Error clearing session: " + e.message);
    }
    return;
  }

  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(renderPage());
});

server.listen(QR_PAGE_PORT, "0.0.0.0", () =>
  console.log(
    "Open http://localhost:" + QR_PAGE_PORT + " in your browser to scan the QR"
  )
);

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState("./session");
  const { version } = await fetchLatestBaileysVersion();

  // If there's no saved session, say so immediately; otherwise say we're trying to reuse it.
  connectionStatus = state.creds?.registered
    ? "reconnecting to WhatsApp using saved session..."
    : "no session found — waiting for QR to be generated...";

  const sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    logger: pino({ level: "silent" }),
    browser: ["Restaurant Bot", "Chrome", "1.0.0"],
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (connection === "open") {
      isConnected = true;
      connectionStatus = "CONNECTED ✅ — you can close this page";
      console.log("CONNECTED! The gateway is live.");
      console.log("Send a WhatsApp message to this number and the bot will reply.");
    }

    if (connection === "connecting") {
      if (!isConnected) connectionStatus = "connecting to WhatsApp...";
    }

    if (qr) {
      latestQR = qr;
      qrDataURL = await qrcodeLib.toDataURL(qr);
      connectionStatus = "waiting for you to scan the QR ⏳";
      console.log("New QR generated — refresh http://localhost:" + QR_PAGE_PORT);
      try {
        const pairingCode = await sock.requestPairingCode(MY_NUMBER);
        latestPairingCode = pairingCode;
        console.log("Pairing code: " + pairingCode);
      } catch (e) {
        console.error("Pairing code failed:", e.message);
      }
    }

    if (connection === "close") {
      isConnected = false;
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code !== DisconnectReason.loggedOut) {
        connectionStatus = "disconnected — reconnecting in 3s...";
        console.log("Reconnecting...");
        setTimeout(start, 3000);
      } else {
        connectionStatus = "logged out. Restart it after scanning the QR again.";
        console.log("Logged out. Delete ./session folder and restart to link again.");
      }
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    const msg = messages[0];
    if (!msg.message || msg.key.fromMe) return;

    const text =
      msg.message.conversation ||
      msg.message.extendedTextMessage?.text ||
      msg.message.imageMessage?.caption ||
      msg.message.buttonsResponseMessage?.displayText ||
      "";
    if (!text.trim()) return;

    const sender = msg.key.participant || msg.key.remoteJid;
    const phone = sender.split("@")[0];
    console.log("From " + phone + ": " + text);

    try {
      const res = await fetch(BOT_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender: phone, message: text }),
      });
      const data = await res.json();
      const reply = data.reply || "Something went wrong.";

      await sock.sendMessage(msg.key.remoteJid, { text: reply });
      console.log("Replied to " + phone);
    } catch (err) {
      console.error("Gateway error:", err.message);
    }
  });
}

start();
