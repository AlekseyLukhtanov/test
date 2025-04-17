import os
import csv
import json
import asyncio
import datetime
from telethon import TelegramClient, events
from telethon.tl.types import UserStatusRecently, UserStatusOnline, User, Message, MessageService
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from tqdm.asyncio import tqdm
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

user_data = {}

# HTTP для Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', 10000), SimpleHandler).serve_forever(), daemon=True).start()

# Telegram-бот
bot = TelegramClient('bot_session', <YOUR_API_ID>, '<YOUR_API_HASH>').start(bot_token='<YOUR_BOT_TOKEN>')

DOWNLOADS_PATH = os.path.expanduser("~/Downloads")

# Вспомогательные функции
def create_output_folder(project_name):
    folder_path = os.path.join(DOWNLOADS_PATH, project_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def save_to_csv(users, folder_path):
    chunks = [users[i:i+50] for i in range(0, len(users), 50)]
    for idx, chunk in enumerate(chunks, 1):
        filename = os.path.join(folder_path, f"users_part_{idx}.csv")
        with open(filename, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["username"])
            for user in chunk:
                writer.writerow([user])

def is_active(user):
    status = user.status
    if isinstance(status, (UserStatusRecently, UserStatusOnline)):
        return True
    elif hasattr(status, 'was_online'):
        delta = datetime.datetime.now(datetime.timezone.utc) - status.was_online
        return delta.days <= 2
    return False

async def get_participants(client, entity):
    participants = []
    offset = 0
    limit = 100
    while True:
        part = await client(GetParticipantsRequest(
            channel=entity,
            filter=ChannelParticipantsSearch(""),
            offset=offset,
            limit=limit,
            hash=0
        ))
        if not part.users:
            break
        participants.extend(part.users)
        offset += len(part.users)
        await asyncio.sleep(1)
    return participants

async def get_users_from_messages(client, entity, message_limit):
    user_ids = set()
    async for message in client.iter_messages(entity, limit=message_limit):
        if isinstance(message, (Message, MessageService)) and message.sender_id:
            user_ids.add(message.sender_id)
        await asyncio.sleep(0.05)
    users = []
    for uid in user_ids:
        try:
            user = await client.get_entity(uid)
            users.append(user)
        except:
            continue
        await asyncio.sleep(0.1)
    return users

async def filter_users(users):
    filtered = []
    for user in users:
        if not isinstance(user, User):
            continue
        if user.bot or not is_active(user) or not user.username:
            continue
        filtered.append(user.username)
        await asyncio.sleep(0.01)
    return list(set(filtered))

@bot.on(events.NewMessage)
async def handler(event):
    chat_id = event.chat_id
    text = event.raw_text.strip()

    if chat_id not in user_data:
        user_data[chat_id] = {"step": "api_id"}
        await event.respond("👋 Привет! Введи свой `api_id`:")
        return

    user_state = user_data[chat_id]

    if user_state["step"] == "api_id":
        user_state["api_id"] = int(text)
        user_state["step"] = "api_hash"
        await event.respond("✅ Отлично! Теперь введи свой `api_hash`:")
    elif user_state["step"] == "api_hash":
        user_state["api_hash"] = text
        user_state["step"] = "phone_number"
        await event.respond("📞 Введи номер телефона, привязанный к Telegram:")
    elif user_state["step"] == "phone_number":
        user_state["phone_number"] = text
        user_state["step"] = "project_link"
        await event.respond("🔗 Введи ссылку на канал или группу:")
    elif user_state["step"] == "project_link":
        user_state["project_link"] = text
        user_state["step"] = "project_name"
        await event.respond("📁 Введи название проекта:")
    elif user_state["step"] == "project_name":
        user_state["project_name"] = text
        user_state["step"] = "ask_participants"
        await event.respond("Собирать участников из вкладки 'Участники'? (да/нет)")
    elif user_state["step"] == "ask_participants":
        user_state["use_participants"] = text.lower() == "да"
        user_state["step"] = "ask_messages"
        await event.respond("Собирать пользователей из сообщений? (да/нет)")
    elif user_state["step"] == "ask_messages":
        user_state["use_messages"] = text.lower() == "да"
        user_state["step"] = "ask_limit"
        await event.respond("Сколько сообщений анализировать?")
    elif user_state["step"] == "ask_limit":
        user_state["message_limit"] = int(text)
        await event.respond("🚀 Начинаю сбор данных...")
        asyncio.create_task(start_collection(chat_id, user_state, event))
        user_state["step"] = "done"

async def start_collection(chat_id, config, event):
    try:
        session_name = f"session_{chat_id}"
        client = TelegramClient(session_name, config["api_id"], config["api_hash"])
        await client.start(config["phone_number"])
        entity = await client.get_entity(config["project_link"])

        output_folder = create_output_folder(config["project_name"])

        users = []
        if config.get("use_participants"):
            users += await get_participants(client, entity)
        if config.get("use_messages"):
            users += await get_users_from_messages(client, entity, config["message_limit"])

        final_usernames = await filter_users(users)
        save_to_csv(final_usernames, output_folder)

        await event.respond(f"✅ Сохранено {len(final_usernames)} username в: {output_folder}")
        await client.disconnect()

    except Exception as e:
        await event.respond(f"❌ Ошибка: {e}")

bot.run_until_disconnected()
