import os
import json
import asyncio
import aiohttp
import asyncpg
import threading
import queue
from datetime import datetime
from aiohttp import web
from chat_downloader import ChatDownloader
from telegram_handler import TelegramHandler

# Create web app for health checks
app = web.Application()

async def health_check(request):
    return web.Response(text="Service is running")

app.router.add_get("/", health_check)
app.router.add_get("/health", health_check)

async def self_ping():
    """Periodically ping our own service to prevent Render free tier from sleeping"""
    if not RENDER_SERVICE_URL:
        print("RENDER_SERVICE_URL not set, skipping self-ping")
        return
        
    service_url = f"{RENDER_SERVICE_URL.rstrip('/')}/health"
    print(f"Starting self-ping to {service_url}")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(service_url) as response:
                    if response.status == 200:
                        print("Self-ping successful")
                    else:
                        print(f"Self-ping failed with status {response.status}")
            except Exception as e:
                print(f"Self-ping error: {str(e)}")
            await asyncio.sleep(60 * 14)  # Ping every 14 minutes (Render free tier sleeps after 15 minutes)

async def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")
    
    # Start the self-ping task
    asyncio.create_task(self_ping())

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
            sent_to_telegram BOOLEAN DEFAULT FALSE,
            telegram_sent_at TIMESTAMP WITH TIME ZONE,
            data JSONB
        )
    ''')
    await conn.close()

# Database operations
async def is_user_sent_to_telegram(pool, channel_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            'SELECT sent_to_telegram FROM youtube_users WHERE channel_id = $1',
            channel_id
        ) or False

async def save_user(pool, channel_id, channel_name, channel_url, data):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO youtube_users (channel_id, channel_name, channel_url, data, sent_to_telegram)
            VALUES ($1, $2, $3, $4, FALSE)
            ON CONFLICT (channel_id) DO NOTHING
        ''', channel_id, channel_name, channel_url, json.dumps(data))

async def mark_user_sent_to_telegram(pool, channel_id):
    async with pool.acquire() as conn:
        await conn.execute('''
            UPDATE youtube_users 
            SET sent_to_telegram = TRUE, telegram_sent_at = CURRENT_TIMESTAMP 
            WHERE channel_id = $1
        ''', channel_id)

# Server endpoints
async def handle_health_check(request):
    return aiohttp.web.Response(text="OK")

async def handle_ping(request):
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return aiohttp.web.json_response({
        "status": "alive",
        "timestamp": current_time,
        "message": "Service is active and monitoring YouTube chat"
    })

async def start_server():
    app = aiohttp.web.Application()
    # Add routes
    app.router.add_get('/', handle_health_check)
    app.router.add_get('/ping', handle_ping)  # New ping endpoint
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    
    # Render assigns a port via the PORT environment variable
    port = int(os.environ.get('PORT', 10000))
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Health check server running on port {port}")
    
    # Important: We need to keep this information
    print(f"Server started on port {port}")
    print(f"Listening on http://0.0.0.0:{port}")
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
    retry_delay = 60  # seconds
    initial_retry_delay = retry_delay
    max_retry_delay = 300  # 5 minutes max between retries
    
    # Start web server first
    await start_web_server()
    print("Web server started successfully")
    
    # Initialize services
    await init_db()
    pool = await asyncpg.create_pool(DATABASE_URL)
    telegram_handler = TelegramHandler(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID)
    
    livestream_url = f'https://www.youtube.com/watch?v={YOUTUBE_VIDEO_ID}'
    print(f"Monitoring chat for video: {livestream_url}")
    
    attempt = 1
    while True:  # Continuous retry loop
        try:
            # Set up ChatDownloader with cookies
            if os.path.exists(COOKIES_FILE):
                print(f"Using cookies file: {COOKIES_FILE}")
                chat_downloader = ChatDownloader(cookies=COOKIES_FILE)
            else:
                print("Warning: Cookies file not found, trying without authentication")
                chat_downloader = ChatDownloader()
            
            print("Connecting to YouTube chat...")
            chat = chat_downloader.get_chat(livestream_url)
            print("Successfully connected to YouTube chat! Starting to monitor messages...")
            
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
                            # Save the user first (won't duplicate due to ON CONFLICT DO NOTHING)
                            await save_user(pool, channel_id, channel_name, channel_url, author)
                            
                            # Check if we've already sent this user to Telegram
                            if await is_user_sent_to_telegram(pool, channel_id):
                                continue
                            
                            # Prepare channel URL if not provided
                            if not channel_url and channel_id:
                                channel_url = f'https://www.youtube.com/channel/{channel_id}'
                            
                            # Send to Telegram
                            try:
                                await telegram_handler.send_message_with_retry(
                                    channel_name=channel_name,
                                    channel_url=channel_url,
                                    timestamp=now,
                                    profile_pic_url=profile_pic_url,
                                    session=session
                                )
                                # Mark as sent only after successful Telegram send
                                await mark_user_sent_to_telegram(pool, channel_id)
                                print(f"Successfully sent and marked user {channel_name} ({channel_id})")
                            except Exception as send_error:
                                print(f"Failed to send user to Telegram: {channel_name} ({channel_id}): {send_error}")
                                # Don't mark as sent if there was an error
                    except Exception as msg_error:
                        print(f"Error processing message: {msg_error}")
                        continue
            
            # If we get here without errors, break the retry loop
            break
            
        except Exception as e:
            print("Error in chat monitoring:")
            print("1. Verify that YOUTUBE_VIDEO_ID is correct and the video is live")
            print("2. Ensure cookies.txt is properly formatted and contains valid authentication")
            print("3. Check your network connection")
            print(f"Error details: {str(e)}")
            raise  # Re-raise the exception
    
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
                # This check is now handled by is_user_sent_to_telegram
                
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
