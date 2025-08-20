# YouTube Live Chat Monitor

A Python bot that monitors YouTube livestream chat and automatically sends new user information to a Telegram channel. The bot captures user profile pictures and channel information, helping you track new participants in your livestream chat.

## Features

- 🔍 Monitors YouTube livestream chat in real-time
- 📸 Captures user profile pictures
- 🔗 Includes clickable channel links
- 🕒 Records date and time of first appearance
- 📊 PostgreSQL database for tracking unique users
- 🔄 Prevents duplicate notifications
- 🟢 24/7 operation on Render with keep-alive system
- 🍪 Supports YouTube authentication via cookies

## Message Format

Each new user notification includes:
```
✨ Name: [User's Name]
📺 Channel: [Click Here]
⏰ Date/Time: YYYY-MM-DD HH:MM:SS
🤖 Agent: @CyberWo9f
```

## Prerequisites

- Python 3.8 or higher
- PostgreSQL database (provided by Render)
- Telegram Bot Token
- YouTube cookies file (for authentication)
- Render.com account for hosting

## Environment Variables

Set these in your Render dashboard:

| Variable | Description |
|----------|-------------|
| `YOUTUBE_VIDEO_ID` | Your YouTube livestream video ID |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHANNEL_ID` | Your Telegram channel ID |
| `DATABASE_URL` | PostgreSQL database URL (auto-set by Render) |
| `RENDER_SERVICE_URL` | Your Render service URL (for keep-alive) |
| `COOKIES_FILE` | Path to cookies file (default: cookies.txt) |

## Local Development

1. Clone the repository:
```bash
git clone [your-repo-url]
cd ChannelScrape
```

2. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Place your `cookies.txt` file in the project root

5. Set up environment variables in a `.env` file (not included in git)

6. Run the bot:
```bash
python yt_to_telegram.py
```

## Deployment to Render

1. Push your code to GitHub

2. In Render dashboard:
   - Create new Web Service
   - Connect your GitHub repository
   - Select "Docker" as environment
   - Set required environment variables
   - Deploy!

3. After deployment:
   - Copy your service URL
   - Add it as `RENDER_SERVICE_URL` in environment variables
   - The keep-alive system will prevent the service from sleeping

## Database Schema

The PostgreSQL database tracks user information:

```sql
CREATE TABLE youtube_users (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT,
    channel_url TEXT,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    data JSONB
);
```

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is licensed under the MIT License - see the LICENSE file for details.
