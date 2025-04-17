import os
import json
import csv
import asyncio
import datetime
from tqdm.asyncio import tqdm
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import (
    ChannelParticipantsSearch, UserStatusRecently,
    UserStatusOnline, ChannelParticipantsAdmins,
    MessageService, Message
)
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")


DOWNLOADS_PATH = os.path.expanduser("~/Downloads")

def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка при загрузке config.json: {e}")
        exit(1)

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

def save_error_log(folder_path, message):
    with open(os.path.join(folder_path, "errors.log"), "a", encoding="utf-8") as f:
        f.write(message + "\n")

def is_active(user):
    status = user.status
    if isinstance(status, (UserStatusRecently, UserStatusOnline)):
        return True
    elif hasattr(status, 'was_online'):
        delta = datetime.datetime.now(datetime.timezone.utc) - status.was_online
        return delta.days <= 2
    return False

async def get_participants(client, entity):
    print("\U0001F4E5 Получаем участников через GetParticipantsRequest...")
    participants = []
    offset = 0
    limit = 100
    try:
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
    except Exception as e:
        print("⚠️ Не удалось получить участников напрямую.")
        raise e
    return participants

async def get_users_from_messages(client, entity, message_limit):
    print(f"\U0001F4AC Собираем пользователей из истории сообщений (до {message_limit} сообщений)...")
    user_ids = set()
    async for message in tqdm(client.iter_messages(entity, limit=message_limit), desc="Анализ сообщений"):
        if isinstance(message, (Message, MessageService)) and message.sender_id:
            user_ids.add(message.sender_id)
        await asyncio.sleep(0.05)
    users = []
    for uid in tqdm(user_ids, desc="Загрузка пользователей"):
        try:
            user = await client.get_entity(uid)
            users.append(user)
        except:
            continue
        await asyncio.sleep(0.1)
    return users

async def get_users_from_comments(client, entity):
    print("\U0001F5E8️ Собираем пользователей из комментариев (если есть)...")
    users = []
    try:
        async for message in tqdm(client.iter_messages(entity, limit=500), desc="Проверка комментов"):
            if message.replies and message.replies.comments:
                async for comment in client.iter_messages(message.replies.channel_id, reply_to=message.id):
                    if comment.sender_id:
                        try:
                            user = await client.get_entity(comment.sender_id)
                            users.append(user)
                        except:
                            continue
                    await asyncio.sleep(0.1)
    except:
        print("⚠️ Комментарии не обнаружены или не поддерживаются.")
    return users

async def filter_users(client, users, spammer_ids):
    print("⚡ Фильтрация по активности и ролям...")
    filtered = []
    for user in tqdm(users, desc="Фильтруем"):
        if user.bot or user.id in spammer_ids:
            continue
        if not is_active(user):
            continue
        if not user.username:
            continue
        try:
            participant = await client.get_participant(user.id)
            if getattr(participant, 'admin_rights', None):
                continue
        except:
            pass
        filtered.append(user.username)
        await asyncio.sleep(0.05)
    return list(set(filtered))

async def detect_spammers(client, entity, message_limit):
    print(f"\U0001F9E0 Определяем спамеров (по {message_limit} сообщениям)...")
    cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40)
    msg_counts = {}
    async for msg in tqdm(client.iter_messages(entity, limit=message_limit), desc="Сканируем"):
        if msg.date < cutoff_date or not msg.sender_id or not msg.text:
            continue
        key = (msg.sender_id, msg.text.strip())
        msg_counts[key] = msg_counts.get(key, 0) + 1
        await asyncio.sleep(0.05)
    spammers = {uid for (uid, _), count in msg_counts.items() if count > 2}
    return spammers

async def main():
    config = load_config()
    project_link = input("\U0001F517 Введите ссылку или username Telegram-группы: ").strip()
    project_name = input("\U0001F4C2 Введите название проекта: ").strip()
    output_folder = create_output_folder(project_name)

    # Запросы для фильтров и источников
    use_participants = input("Собирать участников из вкладки 'Участники' (да/нет)? ").strip().lower() == 'да'
    use_messages = input("Собирать пользователей из сообщений (да/нет)? ").strip().lower() == 'да'
    use_comments = input("Собирать пользователей из комментариев (да/нет)? ").strip().lower() == 'да'
    message_limit = int(input("Введите количество сообщений для анализа: ").strip())

    client = TelegramClient("session", config["api_id"], config["api_hash"])

    try:
        await client.start(config["phone_number"])
        entity = await client.get_entity(project_link)

        users = []

        if use_participants:
            try:
                users += await get_participants(client, entity)
            except Exception as e:
                save_error_log(output_folder, f"GetParticipantsRequest error: {e}")

        if use_messages:
            try:
                users += await get_users_from_messages(client, entity, message_limit)
            except Exception as e:
                save_error_log(output_folder, f"iter_messages error: {e}")

        if use_comments:
            try:
                users += await get_users_from_comments(client, entity)
            except Exception as e:
                save_error_log(output_folder, f"comments error: {e}")

        print(f"📦 Всего собранных пользователей: {len(users)}")

        spammer_ids = await detect_spammers(client, entity, message_limit)
        final_usernames = await filter_users(client, users, spammer_ids)

        save_to_csv(final_usernames, output_folder)
        print(f"✅ Сохранено {len(final_usernames)} username в: {output_folder}")

    except Exception as e:
        save_error_log(output_folder, f"Critical error: {e}")
        print(f"❌ Ошибка: {e}")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
