import re
from io import BytesIO
from telegram import Bot
import asyncio

class TelegramHandler:
    def __init__(self, bot_token, channel_id):
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id

    @staticmethod
    def escape_md(text):
        """Escape markdown characters in text"""
        chars = r'_\[\]\(\)~`>#+\-=|{}.!'
        return re.sub(rf'([{chars}])', r'\\\1', str(text))

    def format_message(self, channel_name, channel_url, timestamp):
        """Format message for Telegram with proper escaping"""
        safe_channel_name = self.escape_md(channel_name)
        safe_timestamp = self.escape_md(timestamp)
        safe_agent = self.escape_md('@CyberWo9f')
        
        if channel_url:
            # Only escape parentheses in URLs
            safe_url = channel_url.replace(')', '\\)').replace('(', '\\(')
            channel_link = f'[Click Here]({safe_url})'
        else:
            channel_link = self.escape_md('None')
        
        return (
            f"✨ *Name:* {safe_channel_name}\n"
            f"📺 *Channel:* {channel_link} 🔗\n"
            f"⏰ *Date&Time:* {safe_timestamp}\n"
            f"🤖 *Agent:* {safe_agent} ✅"
        )

    async def send_message_with_retry(self, channel_name, channel_url, timestamp, profile_pic_url=None, session=None, max_attempts=3):
        """Send message to Telegram with retry logic"""
        caption = self.format_message(channel_name, channel_url, timestamp)

        for attempt in range(1, max_attempts + 1):
            try:
                if profile_pic_url and session:
                    async with session.get(profile_pic_url) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            img_file = BytesIO(img_bytes)
                            img_file.name = 'profile.jpg'
                            await self.bot.send_photo(
                                chat_id=self.channel_id,
                                photo=img_file,
                                caption=caption,
                                parse_mode='MarkdownV2'
                            )
                            print(f"Sent photo for {channel_name}")
                        else:
                            await self.bot.send_message(
                                chat_id=self.channel_id,
                                text=caption,
                                parse_mode='MarkdownV2'
                            )
                            print(f"Sent info for {channel_name} (no image, HTTP {resp.status})")
                else:
                    await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=caption,
                        parse_mode='MarkdownV2'
                    )
                    print(f"Sent info for {channel_name} (no image)")
                
                # Add delay after successful send to avoid rate limits
                await asyncio.sleep(3)
                return True

            except Exception as e:
                if 'RetryAfter' in str(type(e)) and attempt < max_attempts:
                    retry_after = int(str(e).split()[-2])
                    print(f"Rate limit hit, waiting {retry_after} seconds before retry {attempt}/{max_attempts}")
                    await asyncio.sleep(retry_after)
                else:
                    print(f"Error sending message: {e}")
                    if attempt < max_attempts:
                        await asyncio.sleep(5)
                    else:
                        print(f"Failed to send after {max_attempts} attempts")
                        return False
        
        return False
