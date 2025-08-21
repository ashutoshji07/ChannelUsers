import os
import json
import asyncio
import aiohttp
import asyncpg
import threading
import queue
from datetime import datetime
from chat_downloader import ChatDownloader
from telegram_handler import TelegramHandler

# --- CONFIGURATION ---
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
    conn = await asyncpg.connect(DATABASE_URL)
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

# Database operations
async def is_user_exists(pool, channel_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            'SELECT EXISTS(SELECT 1 FROM youtube_users WHERE channel_id = $1)',
            channel_id
        )

async def save_user(pool, channel_id, channel_name, channel_url, data):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO youtube_users (channel_id, channel_name, channel_url, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (channel_id) DO NOTHING
        ''', channel_id, channel_name, channel_url, json.dumps(data))

# Health check server
async def handle_health_check(request):
    return aiohttp.web.Response(text="OK")

async def start_server():
    app = aiohttp.web.Application()
    app.router.add_get('/', handle_health_check)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000))
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Health check server running on port {port}")
    return runner

# Helper to convert sync iterator to async iterator
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

# Main chat monitoring function
async def main():
    max_retries = 3
    retry_delay = 60  # seconds
    
    # Initialize services
    await init_db()
    pool = await asyncpg.create_pool(DATABASE_URL)
    telegram_handler = TelegramHandler(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID)
    
    livestream_url = f'https://www.youtube.com/watch?v={YOUTUBE_VIDEO_ID}'
    print(f"Monitoring chat for video: {livestream_url}")
    
    for attempt in range(max_retries):
        try:
            # Set up ChatDownloader with cookies
            if os.path.exists(COOKIES_FILE):
                print(f"Using cookies file: {COOKIES_FILE}")
                chat_downloader = ChatDownloader(cookies=COOKIES_FILE)
            else:
                print("Warning: Cookies file not found, trying without authentication")
                chat_downloader = ChatDownloader()
            
            # Test the connection before starting the main loop
            print(f"Attempt {attempt + 1}/{max_retries}: Connecting to YouTube chat...")
            chat = chat_downloader.get_chat(livestream_url)
            
            # Try to get the first message to verify the connection
            test_message = next(chat, None)
            if test_message is None:
                raise Exception("No messages available in the chat")
            
            print("Successfully connected to YouTube chat!")
            # Reset chat for the main loop
            chat = chat_downloader.get_chat(livestream_url)
            
            # If we reach here, connection is successful
            async with aiohttp.ClientSession() as session:
                async for message in _to_async_iter(chat):
                    try:
                        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        author = message.get('author', {})
                        channel_id = author.get('id')
                        channel_name = author.get('name')
                        channel_url = author.get('url')
                        images = author.get('images', [])
                        profile_pic_url = images[0]['url'] if images else None
                        
                        if channel_id:
                            if await is_user_exists(pool, channel_id):
                                continue
                            
                            await save_user(pool, channel_id, channel_name, channel_url, author)
                            
                            if not channel_url and channel_id:
                                channel_url = f'https://www.youtube.com/channel/{channel_id}'
                            
                            await telegram_handler.send_message_with_retry(
                                channel_name=channel_name,
                                channel_url=channel_url,
                                timestamp=now,
                                profile_pic_url=profile_pic_url,
                                session=session
                            )
                    except Exception as msg_error:
                        print(f"Error processing message: {msg_error}")
                        continue
            
            # If we get here without errors, break the retry loop
            break
            
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                print("All attempts failed. Please check:")
                print("1. Verify that YOUTUBE_VIDEO_ID is correct and the video is live")
                print("2. Ensure cookies.txt is properly formatted and contains valid authentication")
                print("3. Check your network connection")
                raise  # Re-raise the last exception
    
    chat = chat_downloader.get_chat(livestream_url)
    async with aiohttp.ClientSession() as session:
        async for message in _to_async_iter(chat):
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            author = message.get('author', {})
            channel_id = author.get('id')
            channel_name = author.get('name')
            channel_url = author.get('url')
            images = author.get('images', [])
            profile_pic_url = images[0]['url'] if images else None
            
            if channel_id:
                if await is_user_exists(pool, channel_id):
                    continue
                
                await save_user(pool, channel_id, channel_name, channel_url, author)
                
                if not channel_url and channel_id:
                    channel_url = f'https://www.youtube.com/channel/{channel_id}'
                
                await telegram_handler.send_message_with_retry(
                    channel_name=channel_name,
                    channel_url=channel_url,
                    timestamp=now,
                    profile_pic_url=profile_pic_url,
                    session=session
                )

# Keep alive task
async def keep_alive():
    if not RENDER_SERVICE_URL:
        return
    
    runner = await start_server()
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    await asyncio.sleep(14 * 60)  # 14 minutes
                    async with session.get(RENDER_SERVICE_URL) as response:
                        print(f"Keep-alive ping status: {response.status}")
                except Exception as e:
                    print(f"Keep-alive ping failed: {e}")
    finally:
        await runner.cleanup()

async def start_services():
    try:
        await asyncio.gather(
            keep_alive(),
            main()
        )
    except Exception as e:
        print(f"Service error: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(start_services())
