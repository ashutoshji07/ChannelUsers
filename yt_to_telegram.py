# YouTube Live Chat to Telegram Bot
# This script will monitor a YouTube livestream chat and send new users' channel info to a Telegram channel.



import os
import asyncio
import aiohttp
from datetime import datetime
from chat_downloader import ChatDownloader
from telegram import Bot


# --- CONFIGURATION ---
import os
import asyncpg
import json
import asyncio
from aiohttp import ClientSession
import telegram

# Get configuration from environment variables
RENDER_SERVICE_URL = os.getenv('RENDER_SERVICE_URL')  # Your Render service URL
YOUTUBE_VIDEO_ID = os.getenv('YOUTUBE_VIDEO_ID')  # Your YouTube livestream video ID
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # Your Telegram bot token
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')  # Your Telegram channel ID
DATABASE_URL = os.getenv('DATABASE_URL')  # Render PostgreSQL database URL
COOKIES_FILE = os.getenv('COOKIES_FILE', 'cookies.txt')  # Your Netscape format cookies file

# Validate required environment variables
required_vars = {
    'YOUTUBE_VIDEO_ID': YOUTUBE_VIDEO_ID,
    'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
    'TELEGRAM_CHANNEL_ID': TELEGRAM_CHANNEL_ID,
    'DATABASE_URL': DATABASE_URL
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Database initialization
async def init_db():
    # Connect to the database
    conn = await asyncpg.connect(DATABASE_URL)
    
    # Create tables if they don't exist
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS youtube_users (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            channel_url TEXT,
            first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            data JSONB
        )
    ''')
    
    await conn.close()

# Check if user exists in database
async def is_user_exists(pool, channel_id):
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            'SELECT EXISTS(SELECT 1 FROM youtube_users WHERE channel_id = $1)',
            channel_id
        )
        return result

# Save user to database
async def save_user(pool, channel_id, channel_name, channel_url, data):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO youtube_users (channel_id, channel_name, channel_url, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (channel_id) DO NOTHING
        ''', channel_id, channel_name, channel_url, json.dumps(data))


# --- INITIALIZE TELEGRAM BOT ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# --- TRACK USERS ---
sent_users = set()


# --- MAIN FUNCTION ---
async def main():
    # Initialize database
    await init_db()
    
    # Create database connection pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    
    livestream_url = f'https://www.youtube.com/watch?v={YOUTUBE_VIDEO_ID}'
    
    # Set up ChatDownloader with cookies
    if os.path.exists(COOKIES_FILE):
        print(f"Using cookies file: {COOKIES_FILE}")
        chat_downloader = ChatDownloader(cookies=COOKIES_FILE)
    else:
        print("Warning: Cookies file not found, trying without authentication")
        chat_downloader = ChatDownloader()
    
    chat = chat_downloader.get_chat(livestream_url)
    async with aiohttp.ClientSession() as session:
        async for message in _to_async_iter(chat):
            # Get current time for each message
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            author = message.get('author', {})
            channel_id = author.get('id')
            channel_name = author.get('name')
            channel_url = author.get('url')
            images = author.get('images', [])
            profile_pic_url = images[0]['url'] if images else None
            if channel_id:
                # Check if user already exists in database
                if not await is_user_exists(pool, channel_id):
                    # Save user to database
                    await save_user(pool, channel_id, channel_name, channel_url, author)
                    
                    # Get current time
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Format with bold for name and channel, and include date/time
                    # Format channel as clickable link if available
                # Fallback: construct channel URL from channel_id if missing
                if not channel_url and channel_id:
                    channel_url = f'https://www.youtube.com/channel/{channel_id}'
                channel_link = channel_url if channel_url else 'None'
                if channel_url:
                    # Only escape parentheses in URLs, not hyphens
                    safe_url = channel_url.replace(')', '\\)').replace('(', '\\(')
                    channel_link = f'[Click Here]({safe_url})'
                # Escape all MarkdownV2 special chars in text fields
                def escape_md(text):
                    import re
                    chars = r'_\[\]\(\)~`>#+\-=|{}.!'  # removed * from chars to allow bold
                    return re.sub(rf'([{chars}])', r'\\\1', str(text))

                safe_channel_name = escape_md(channel_name)
                safe_now = escape_md(now)
                safe_agent = escape_md('@CyberWo9f')
                # Format channel as a "Click Here" link
                if channel_url:
                    # Only escape parentheses in URLs
                    safe_url = channel_url.replace(')', '\\)').replace('(', '\\(')
                    channel_link = f'[Click Here]({safe_url})'
                else:
                    channel_link = escape_md('None')
                # Format the caption with only labels in bold
                caption = (
                    f"✨ *Name:* {safe_channel_name}\n"
                    f"📺 *Channel:* {channel_link} 🔗\n"
                    f"⏰ *Date&Time:* {safe_now}\n"
                    f"🤖 *Agent:* {safe_agent} ✅"
                )
                async def send_with_retry(attempt=1, max_attempts=3):
                    try:
                        if profile_pic_url:
                            async with session.get(profile_pic_url) as resp:
                                if resp.status == 200:
                                    img_bytes = await resp.read()
                                    from io import BytesIO
                                    img_file = BytesIO(img_bytes)
                                    img_file.name = 'profile.jpg'
                                    await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=img_file, caption=caption, parse_mode='MarkdownV2')
                                    print(f"Sent photo for {channel_name}")
                                    # Add delay after successful send
                                    await asyncio.sleep(3)
                                else:
                                    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=caption, parse_mode='MarkdownV2')
                                    print(f"Sent info for {channel_name} (no image, HTTP {resp.status})")
                                    await asyncio.sleep(3)
                        else:
                            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=caption, parse_mode='MarkdownV2')
                            print(f"Sent info for {channel_name} (no image)")
                            await asyncio.sleep(3)
                    except Exception as e:
                        if 'RetryAfter' in str(type(e)) and attempt < max_attempts:
                            retry_after = int(str(e).split()[-2])  # Extract seconds from error message
                            print(f"Rate limit hit, waiting {retry_after} seconds before retry {attempt}/{max_attempts}")
                            await asyncio.sleep(retry_after)
                            await send_with_retry(attempt + 1, max_attempts)
                        else:
                            print(f"Failed to send after {max_attempts} attempts: {str(e)}")
                    except Exception as e:
                        print(f"Error sending message: {e}")
                        if attempt < max_attempts:
                            await asyncio.sleep(5)  # Wait 5 seconds before retry
                            await send_with_retry(attempt + 1, max_attempts)
                
                # Try to send the message with retries
                await send_with_retry()

# Keep alive ping task
async def keep_alive():
    if not RENDER_SERVICE_URL:
        return  # Skip if no service URL is provided
        
    async with ClientSession() as session:
        while True:
            try:
                # Ping the service every 14 minutes
                await asyncio.sleep(14 * 60)  # 14 minutes in seconds
                async with session.get(RENDER_SERVICE_URL) as response:
                    print(f"Keep-alive ping status: {response.status}")
            except Exception as e:
                print(f"Keep-alive ping failed: {e}")

# Helper to convert sync iterator to async iterator
import threading
import queue
def _to_async_iter(sync_iter):
    q = queue.Queue()
    sentinel = object()
    def run():
        for item in sync_iter:
            q.put(item)
        q.put(sentinel)
    threading.Thread(target=run, daemon=True).start()
    async def gen():
        while True:
            item = await asyncio.get_event_loop().run_in_executor(None, q.get)
            if item is sentinel:
                break
            yield item
    return gen()

async def start_services():
    # Run both the main bot and keep-alive ping concurrently
    await asyncio.gather(
        main(),
        keep_alive()
    )

if __name__ == '__main__':
    asyncio.run(start_services())
