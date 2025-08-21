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
        """Escape markdown characters in text for MarkdownV2 format"""
        # Full list of characters that need escaping in MarkdownV2
        chars = r'_*\[\]()~`>#+-=|{}.!'
        escaped = re.sub(rf'([{re.escape(chars)}])', r'\\\1', str(text))
        return escaped

    def sanitize_username(self, username):
        """Sanitize username to prevent formatting issues"""
        # Replace with a simple escaped version to avoid formatting conflicts
        try:
            # First try the standard escaping
            escaped = self.escape_md(username)
            # If username has complex formatting, simplify it further
            if len(username) > 30 or username.count('*') > 2 or username.count('_') > 2:
                # Simplified version with clear indication it's been modified
                return f"{escaped} (sanitized)"
            return escaped
        except Exception:
            # Fallback for any username that causes issues
            return "User (name contains special characters)"
            
    def format_message(self, channel_name, channel_url, timestamp):
        """Format message for Telegram with proper escaping"""
        # For usernames, apply special handling
        safe_channel_name = self.sanitize_username(channel_name)
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
            f"🤖 *Dev:* {safe_agent} ✅"
        )

    async def send_message_with_retry(self, channel_name, channel_url, timestamp, profile_pic_url, session, max_attempts=3):
        """Send message to Telegram with retry logic"""
        # Try to format with markdown first
        try:
            caption = self.format_message(channel_name, channel_url, timestamp)
        except Exception as format_error:
            # If formatting fails, use a simplified format with minimal formatting
            print(f"⚠️ Formatting failed for {channel_name}: {str(format_error)}")
            safe_name = "User (name contains special characters)"
            safe_link = "[Channel Link]" if channel_url else "None"
            caption = f"✨ Name: {safe_name}\n📺 Channel: {safe_link}\n⏰ Time: {timestamp}"
        
        base_delay = 3  # Base delay between messages
        
        for attempt in range(1, max_attempts + 1):
            try:
                # Always try to send with profile picture since it's always available
                try:
                    async with session.get(profile_pic_url) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            img_file = BytesIO(img_bytes)
                            img_file.name = 'profile.jpg'
                            try:
                                await self.bot.send_photo(
                                    chat_id=self.channel_id,
                                    photo=img_file,
                                    caption=caption,
                                    parse_mode='MarkdownV2'
                                )
                                print(f"✅ Sent with photo: {channel_name}")
                            except Exception as markdown_error:
                                if "entities" in str(markdown_error) or "parse" in str(markdown_error).lower():
                                    # If MarkdownV2 parsing fails, try without formatting
                                    print(f"⚠️ Markdown parsing failed, sending without formatting: {str(markdown_error)}")
                                    simple_caption = f"User: {channel_name}\nChannel: {channel_url}\nTime: {timestamp}"
                                    await self.bot.send_photo(
                                        chat_id=self.channel_id,
                                        photo=img_file,
                                        caption=simple_caption,
                                        parse_mode=None  # No parsing
                                    )
                                    print(f"✅ Sent with photo (no formatting): {channel_name}")
                                else:
                                    raise markdown_error
                        else:
                            raise Exception(f"Failed to fetch profile picture: HTTP {resp.status}")
                except Exception as img_error:
                    print(f"⚠️ Image fetch failed for {channel_name}: {str(img_error)}")
                    # Fall back to text-only message if image fetch fails
                    try:
                        await self.bot.send_message(
                            chat_id=self.channel_id,
                            text=caption,
                            parse_mode='MarkdownV2'
                        )
                        print(f"✅ Sent text-only (image failed): {channel_name}")
                    except Exception as text_error:
                        if "entities" in str(text_error) or "parse" in str(text_error).lower():
                            # If MarkdownV2 parsing fails, try without formatting
                            print(f"⚠️ Text formatting failed, sending plain text: {str(text_error)}")
                            simple_text = f"User: {channel_name}\nChannel: {channel_url}\nTime: {timestamp}"
                            await self.bot.send_message(
                                chat_id=self.channel_id,
                                text=simple_text,
                                parse_mode=None  # No parsing
                            )
                            print(f"✅ Sent text-only (no formatting): {channel_name}")
                        else:
                            raise text_error
                
                # Dynamic delay after successful send based on attempt number
                delay = base_delay * attempt
                await asyncio.sleep(delay)
                return True

            except Exception as e:
                error_type = str(type(e).__name__)
                if 'RetryAfter' in error_type:
                    # Handle Telegram rate limit
                    retry_after = int(str(e).split()[-2])
                    print(f"⏳ Rate limit hit for {channel_name}, waiting {retry_after}s (attempt {attempt}/{max_attempts})")
                    await asyncio.sleep(retry_after + 1)  # Add 1 second buffer
                elif attempt < max_attempts:
                    # Other errors, use exponential backoff
                    wait_time = 5 * attempt
                    print(f"❌ Error sending message for {channel_name}: {str(e)}")
                    print(f"⏳ Retrying in {wait_time}s (attempt {attempt}/{max_attempts})")
                    await asyncio.sleep(wait_time)
                else:
                    # Final attempt failed
                    print(f"❌ Failed to send after {max_attempts} attempts for {channel_name}")
                    print(f"Final error: {str(e)}")
                    return False
        
        return False
