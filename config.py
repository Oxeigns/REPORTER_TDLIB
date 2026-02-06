"""
Telegram Reporting Bot Configuration
"""
import os

# Bot Token (Get from @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Owner ID (Your Telegram User ID)
OWNER_ID = int(os.getenv("OWNER_ID", "YOUR_USER_ID_HERE"))

# Force Subscribe Channel/Group
FORCE_SUBSCRIBE_CHANNEL = os.getenv("FORCE_SUBSCRIBE_CHANNEL", "@yourchannel")
FORCE_SUBSCRIBE_CHANNEL_ID = int(os.getenv("FORCE_SUBSCRIBE_CHANNEL_ID", "-1001234567890"))

# Database
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority")
DATABASE_NAME = os.getenv("DATABASE_NAME", "reporting_bot")

# TDLib Settings
TDLIB_API_ID = int(os.getenv("API_ID", "12345"))
TDLIB_API_HASH = os.getenv("API_HASH", "your_api_hash_here")

# Reporting Settings
MAX_REPORTS_PER_BATCH = int(os.getenv("MAX_REPORTS_PER_BATCH", "5000"))
REPORT_DELAY = float(os.getenv("REPORT_DELAY", "1.5"))  # Delay between reports in seconds
MAX_CONCURRENT_REPORTS = int(os.getenv("MAX_CONCURRENT_REPORTS", "200"))

# Required number of IDs for normal users
REQUIRED_IDS_COUNT = 3

# Report Types
REPORT_TYPES = {
    "1": {"name": "Spam", "reason_id": "SPAM"},
    "2": {"name": "Violence", "reason_id": "VIOLENCE"},
    "3": {"name": "Child Abuse", "reason_id": "CHILD_ABUSE"},
    "4": {"name": "Pornography", "reason_id": "PORNOGRAPHY"},
    "5": {"name": "Copyright", "reason_id": "COPYRIGHT"},
    "6": {"name": "Personal Details", "reason_id": "PERSONAL_DETAILS"},
    "7": {"name": "Illegal Drugs", "reason_id": "ILLEGAL_DRUGS"},
    "8": {"name": "Fraud/Scam", "reason_id": "FRAUD"},
}

# Messages
START_MESSAGE = """
🤖 <b>Welcome to Premium Reporting Bot</b>

⚡ This bot helps you report spam/abusive content on Telegram
📌 Features:
   • Multi-account reporting
   • Live progress tracking
   • Fast & efficient
   • 24/7 Available

👇 Press the button below to start!
"""

FORCE_SUBSCRIBE_TEXT = """
⚠️ <b>Join Required Channel</b>

Please join our channel to use this bot:
👉 {channel}

✅ After joining, click "Check Membership"
"""

ID_LOGIN_MESSAGE = """
🔐 <b>ID Login Required</b>

To use reporting features, you need to login with {required} Telegram accounts.

✅ Benefits:
   • Higher success rate
   • Faster reporting
   • More powerful

⚠️ Please provide your phone numbers one by one.

📱 Send your phone number with country code:
Example: +919876543210
"""

REPORT_GUIDE = """
📖 <b>Reporting Guide</b>

<b>Step 1:</b> Login with {required} IDs (if not sudo user)
<b>Step 2:</b> Provide group/channel link to join
<b>Step 3:</b> Provide target link (user/channel/group to report)
<b>Step 4:</b> Select report type
<b>Step 5:</b> Enter number of reports
<b>Step 6:</b> Add description (optional)
<b>Step 7:</b> Bot starts reporting!

⚠️ <b>Note:</b>
• Make sure your accounts are active
• Don't use new accounts
• Use at your own risk
"""

OWNER_HELP = """
👑 <b>Owner Commands</b>

/addsudo [user_id] - Add sudo user
/remsudo [user_id] - Remove sudo user
/sudolist - List all sudo users
/broadcast - Send message to all users
/stats - Bot statistics
/restart - Restart bot
"""
