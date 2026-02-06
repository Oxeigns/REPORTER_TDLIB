"""
Telegram Reporting Bot - Main File
Premium Multi-Account Reporting System
"""
import os
import sys
import uuid
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from telegram.constants import ParseMode

from config import *
from database import Database
from tdlib_client import TDLibManager, ReportWorker

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database and TDLib
db = Database(MONGODB_URI, DATABASE_NAME)
tdlib_manager = TDLibManager()
report_worker = ReportWorker(tdlib_manager, db)

# Conversation States
(
    WAITING_PHONE,
    WAITING_CODE,
    WAITING_PASSWORD,
    WAITING_GROUP_LINK,
    WAITING_TARGET_LINK,
    WAITING_REPORT_TYPE,
    WAITING_REPORT_COUNT,
    WAITING_DESCRIPTION,
    WAITING_BROADCAST
) = range(9)

# ============= KEYBOARD MARKUPS =============

def get_start_keyboard(user_id):
    """Get start keyboard"""
    keyboard = [
        [InlineKeyboardButton("📨 Send Report", callback_data="send_report")],
        [InlineKeyboardButton("📖 Reporting Guide", callback_data="guide")],
        [InlineKeyboardButton("👤 My Account", callback_data="my_account")],
    ]
    
    if user_id == OWNER_ID or db.is_sudo(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
    
    return InlineKeyboardMarkup(keyboard)


def get_force_sub_keyboard():
    """Force subscribe keyboard"""
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_SUBSCRIBE_CHANNEL.replace('@', '')}")],
        [InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_report_types_keyboard():
    """Get report types keyboard"""
    keyboard = []
    for key, value in REPORT_TYPES.items():
        keyboard.append([InlineKeyboardButton(f"{key}. {value['name']}", callback_data=f"rtype_{key}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


def get_owner_keyboard():
    """Owner panel keyboard"""
    keyboard = [
        [InlineKeyboardButton("➕ Add Sudo", callback_data="add_sudo"),
         InlineKeyboardButton("➖ Remove Sudo", callback_data="remove_sudo")],
        [InlineKeyboardButton("📋 Sudo List", callback_data="sudo_list")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")],
        [InlineKeyboardButton("🔄 Restart", callback_data="restart_bot")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_account_keyboard():
    """Account management keyboard"""
    keyboard = [
        [InlineKeyboardButton("🔐 Add Login ID", callback_data="add_id")],
        [InlineKeyboardButton("📱 View My IDs", callback_data="view_ids")],
        [InlineKeyboardButton("🗑 Clear All IDs", callback_data="clear_ids")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============= HELPER FUNCTIONS =============

async def is_user_member(bot, user_id):
    """Check if user is member of force channel"""
    try:
        member = await bot.get_chat_member(FORCE_SUBSCRIBE_CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False


def get_report_status_text(report_id, success, failed, total):
    """Generate live status text"""
    progress = min(100, int((success + failed) / total * 100)) if total > 0 else 0
    bar_length = 20
    filled = int(bar_length * progress / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    return f"""
⚡ <b>Reporting in Progress...</b>

📊 <b>Report ID:</b> <code>{report_id}</code>
📈 <b>Progress:</b> [{bar}] {progress}%

✅ <b>Success:</b> {success}
❌ <b>Failed:</b> {failed}
📊 <b>Total:</b> {total}
🔄 <b>Remaining:</b> {total - success - failed}

⏳ <i>Please wait, this may take some time...</i>
"""


# ============= COMMAND HANDLERS =============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    
    # Add user to database
    db.add_user(user.id, user.username, user.first_name)
    
    # Check if sudo
    is_sudo_user = db.is_sudo(user.id) or user.id == OWNER_ID
    
    # Check force subscribe
    is_member = await is_user_member(context.bot, user.id)
    
    if not is_member and not is_sudo_user:
        await update.message.reply_text(
            FORCE_SUBSCRIBE_TEXT.format(channel=FORCE_SUBSCRIBE_CHANNEL),
            reply_markup=get_force_sub_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Show main menu
    await update.message.reply_text(
        START_MESSAGE,
        reply_markup=get_start_keyboard(user.id),
        parse_mode=ParseMode.HTML
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    user = update.effective_user
    
    if user.id == OWNER_ID:
        await update.message.reply_text(OWNER_HELP, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(REPORT_GUIDE.format(required=REQUIRED_IDS_COUNT), parse_mode=ParseMode.HTML)


# ============= CALLBACK HANDLERS =============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    user = update.effective_user
    data = query.data
    
    await query.answer()
    
    # Check force subscribe for non-sudo users
    is_sudo_user = db.is_sudo(user.id) or user.id == OWNER_ID
    
    if data != "check_membership" and not is_sudo_user:
        is_member = await is_user_member(context.bot, user.id)
        if not is_member:
            # Use edit_message_text or send new message if can't edit
            try:
                await query.edit_message_text(
                    FORCE_SUBSCRIBE_TEXT.format(channel=FORCE_SUBSCRIBE_CHANNEL),
                    reply_markup=get_force_sub_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=FORCE_SUBSCRIBE_TEXT.format(channel=FORCE_SUBSCRIBE_CHANNEL),
                    reply_markup=get_force_sub_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            return
    
    # Handle callbacks
    if data == "check_membership":
        is_member = await is_user_member(context.bot, user.id)
        if is_member:
            try:
                await query.edit_message_text(
                    START_MESSAGE,
                    reply_markup=get_start_keyboard(user.id),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=START_MESSAGE,
                    reply_markup=get_start_keyboard(user.id),
                    parse_mode=ParseMode.HTML
                )
        else:
            await query.answer("❌ You haven't joined the channel yet!", show_alert=True)
    
    elif data == "back_to_main":
        try:
            await query.edit_message_text(
                START_MESSAGE,
                reply_markup=get_start_keyboard(user.id),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text=START_MESSAGE,
                reply_markup=get_start_keyboard(user.id),
                parse_mode=ParseMode.HTML
            )
    
    elif data == "guide":
        guide_text = REPORT_GUIDE.format(required=REQUIRED_IDS_COUNT)
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
        try:
            await query.edit_message_text(
                guide_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text=guide_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
    
    elif data == "my_account":
        await show_account_info(update, context, user.id)
    
    elif data == "send_report":
        await handle_send_report(update, context, user.id)
    
    elif data == "add_id":
        try:
            await query.edit_message_text(
                ID_LOGIN_MESSAGE.format(required=REQUIRED_IDS_COUNT),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text=ID_LOGIN_MESSAGE.format(required=REQUIRED_IDS_COUNT),
                parse_mode=ParseMode.HTML
            )
        context.user_data["waiting_for"] = "phone"
        return WAITING_PHONE
    
    elif data == "view_ids":
        await show_user_ids(update, context, user.id)
    
    elif data == "clear_ids":
        db.remove_all_accounts(user.id)
        await query.answer("✅ All IDs cleared!", show_alert=True)
        await show_account_info(update, context, user.id)
    
    elif data.startswith("rtype_"):
        report_type = data.split("_")[1]
        context.user_data["report_type"] = REPORT_TYPES[report_type]["reason_id"]
        context.user_data["report_type_name"] = REPORT_TYPES[report_type]["name"]
        
        try:
            await query.edit_message_text(
                f"✅ Selected: <b>{REPORT_TYPES[report_type]['name']}</b>\n\n"
                f"🔢 Now enter the number of reports you want to send:\n"
                f"(Max: {MAX_REPORTS_PER_BATCH})",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"✅ Selected: <b>{REPORT_TYPES[report_type]['name']}</b>\n\n"
                     f"🔢 Now enter the number of reports you want to send:\n"
                     f"(Max: {MAX_REPORTS_PER_BATCH})",
                parse_mode=ParseMode.HTML
            )
        context.user_data["waiting_for"] = "report_count"
        return WAITING_REPORT_COUNT
    
    elif data == "owner_panel":
        if user.id != OWNER_ID and not db.is_sudo(user.id):
            await query.answer("❌ You are not authorized!", show_alert=True)
            return
        
        if user.id == OWNER_ID:
            try:
                await query.edit_message_text(
                    "👑 <b>Owner Panel</b>\n\nSelect an option:",
                    reply_markup=get_owner_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=user.id,
                    text="👑 <b>Owner Panel</b>\n\nSelect an option:",
                    reply_markup=get_owner_keyboard(),
                    parse_mode=ParseMode.HTML
                )
        else:
            # Sudo user panel
            keyboard = [
                [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
            ]
            try:
                await query.edit_message_text(
                    "⚙️ <b>Sudo Panel</b>\n\nSelect an option:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=user.id,
                    text="⚙️ <b>Sudo Panel</b>\n\nSelect an option:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
    
    elif data == "add_sudo":
        if user.id != OWNER_ID:
            await query.answer("❌ Only owner can add sudo users!", show_alert=True)
            return
        try:
            await query.edit_message_text(
                "➕ <b>Add Sudo User</b>\n\nSend the user ID:",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text="➕ <b>Add Sudo User</b>\n\nSend the user ID:",
                parse_mode=ParseMode.HTML
            )
        context.user_data["waiting_for"] = "sudo_id_add"
    
    elif data == "remove_sudo":
        if user.id != OWNER_ID:
            await query.answer("❌ Only owner can remove sudo users!", show_alert=True)
            return
        try:
            await query.edit_message_text(
                "➖ <b>Remove Sudo User</b>\n\nSend the user ID:",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text="➖ <b>Remove Sudo User</b>\n\nSend the user ID:",
                parse_mode=ParseMode.HTML
            )
        context.user_data["waiting_for"] = "sudo_id_remove"
    
    elif data == "sudo_list":
        await show_sudo_list(update, context)
    
    elif data == "stats":
        await show_stats(update, context)
    
    elif data == "broadcast":
        if user.id != OWNER_ID:
            await query.answer("❌ Only owner can broadcast!", show_alert=True)
            return
        try:
            await query.edit_message_text(
                "📢 <b>Broadcast Message</b>\n\nSend the message you want to broadcast:",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text="📢 <b>Broadcast Message</b>\n\nSend the message you want to broadcast:",
                parse_mode=ParseMode.HTML
            )
        context.user_data["waiting_for"] = "broadcast"
        return WAITING_BROADCAST
    
    elif data == "restart_bot":
        if user.id != OWNER_ID:
            await query.answer("❌ Only owner can restart!", show_alert=True)
            return
        try:
            await query.edit_message_text("🔄 <b>Restarting bot...</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        os._exit(0)
    
    return ConversationHandler.END


async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Show account info"""
    user_data = db.get_user(user_id)
    accounts_count = db.get_active_accounts_count(user_id)
    is_sudo = db.is_sudo(user_id) or user_id == OWNER_ID
    
    status = "👑 Owner" if user_id == OWNER_ID else ("⚡ Sudo" if is_sudo else "👤 User")
    
    text = f"""
👤 <b>My Account</b>

🆔 <b>User ID:</b> <code>{user_id}</code>
📛 <b>Status:</b> {status}
📊 <b>Reports Sent:</b> {user_data.get('report_count', 0) if user_data else 0}
📱 <b>Linked IDs:</b> {accounts_count}
{"✅ Sudo - No ID login required" if is_sudo else f"⚠️ Need {REQUIRED_IDS_COUNT - accounts_count} more ID(s)"}
"""
    
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=get_account_keyboard(), parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_account_keyboard(),
            parse_mode=ParseMode.HTML
        )


async def show_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Show user's linked IDs"""
    accounts = db.get_user_accounts(user_id)
    
    if not accounts:
        await update.callback_query.answer("❌ No IDs linked!", show_alert=True)
        return
    
    text = "📱 <b>Your Linked IDs:</b>\n\n"
    for i, acc in enumerate(accounts, 1):
        phone = acc["phone"][:6] + "****" + acc["phone"][-2:]
        text += f"{i}. <code>{phone}</code>\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="my_account")]]
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )


async def handle_send_report(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Handle send report button"""
    is_sudo = db.is_sudo(user_id) or user_id == OWNER_ID
    accounts_count = db.get_active_accounts_count(user_id)
    
    if not is_sudo and accounts_count < REQUIRED_IDS_COUNT:
        # Need to login IDs first
        keyboard = get_account_keyboard()
        text = (f"⚠️ <b>Login Required</b>\n\n"
                f"You need to login with at least {REQUIRED_IDS_COUNT} Telegram accounts.\n"
                f"Currently linked: {accounts_count}/{REQUIRED_IDS_COUNT}\n\n"
                f"Please add your IDs first.")
        query = update.callback_query
        try:
            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        return
    
    # Show extraction message
    query = update.callback_query
    try:
        await query.edit_message_text(
            "⏳ <b>Please Wait...</b>\n\n"
            "🔍 Extracting saved IDs...\n"
            "⚙️ Setting up reporting system...\n"
            "🔄 Initializing clients...",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text="⏳ <b>Please Wait...</b>\n\n"
                 "🔍 Extracting saved IDs...\n"
                 "⚙️ Setting up reporting system...\n"
                 "🔄 Initializing clients...",
            parse_mode=ParseMode.HTML
        )
    
    # Small delay for effect
    await asyncio.sleep(2)
    
    # Ask for group/channel link
    text = ("✅ <b>Setup Complete!</b>\n\n"
            "📎 Send the group/channel link to join (if needed):\n"
            "• Example: @channelname or https://t.me/channelname\n"
            "• Or send 'skip' if not needed")
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)
    
    context.user_data["waiting_for"] = "group_link"
    return WAITING_GROUP_LINK


async def show_sudo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show sudo users list"""
    sudos = db.get_all_sudos()
    user_id = update.effective_user.id
    
    if not sudos:
        text = "📋 <b>Sudo List</b>\n\nNo sudo users found."
    else:
        text = f"📋 <b>Sudo List ({len(sudos)}):</b>\n\n"
        for sudo in sudos:
            text += f"• <code>{sudo['user_id']}</code>\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="owner_panel")]]
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    stats = db.get_stats()
    user_id = update.effective_user.id
    
    text = f"""
📊 <b>Bot Statistics</b>

👥 <b>Total Users:</b> {stats['total_users']}
⚡ <b>Sudo Users:</b> {stats['total_sudos']}
📱 <b>Active IDs:</b> {stats['total_accounts']}
📨 <b>Total Reports:</b> {stats['total_reports']}
🔄 <b>Active Reports:</b> {stats['active_reports']}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="owner_panel")]]
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )


# ============= MESSAGE HANDLERS =============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user = update.effective_user
    text = update.message.text
    waiting_for = context.user_data.get("waiting_for")
    
    if waiting_for == "phone":
        return await handle_phone_input(update, context, text)
    elif waiting_for == "code":
        return await handle_code_input(update, context, text)
    elif waiting_for == "password":
        return await handle_password_input(update, context, text)
    elif waiting_for == "sudo_id_add":
        return await handle_add_sudo(update, context, text)
    elif waiting_for == "sudo_id_remove":
        return await handle_remove_sudo(update, context, text)
    elif waiting_for == "group_link":
        return await handle_group_link(update, context, text)
    elif waiting_for == "target_link":
        return await handle_target_link(update, context, text)
    elif waiting_for == "report_count":
        return await handle_report_count(update, context, text)
    elif waiting_for == "description":
        return await handle_description(update, context, text)
    
    # Default response
    await update.message.reply_text(
        "❓ Use /start to access the menu",
        reply_markup=get_start_keyboard(user.id)
    )


async def handle_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle phone number input"""
    user = update.effective_user
    
    # Validate phone number
    if not text.startswith("+") or not text[1:].isdigit():
        await update.message.reply_text(
            "❌ Invalid phone number!\n\nPlease send with country code:\nExample: +919876543210",
            parse_mode=ParseMode.HTML
        )
        return WAITING_PHONE
    
    # Save phone
    context.user_data["phone"] = text
    context.user_data["waiting_for"] = "code"
    
    # Send code
    msg = await update.message.reply_text(
        "📲 <b>Sending OTP...</b>\n\nPlease wait...",
        parse_mode=ParseMode.HTML
    )
    
    success, result = await tdlib_manager.send_code(user.id, text, TDLIB_API_ID, TDLIB_API_HASH)
    
    if success:
        context.user_data["phone_code_hash"] = result
        await msg.edit_text(
            "✅ <b>Code sent!</b>\n\n"
            "📱 Check your Telegram app and enter the code:\n"
            "(Example: 12345)",
            parse_mode=ParseMode.HTML
        )
        return WAITING_CODE
    else:
        await msg.edit_text(
            f"❌ <b>Error:</b> {result}\n\nPlease try again with /start",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END


async def handle_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle OTP code input"""
    user = update.effective_user
    phone = context.user_data.get("phone")
    phone_code_hash = context.user_data.get("phone_code_hash")
    
    msg = await update.message.reply_text(
        "🔐 <b>Verifying code...</b>",
        parse_mode=ParseMode.HTML
    )
    
    success, result = await tdlib_manager.verify_code(
        user.id, phone, text, phone_code_hash, TDLIB_API_ID, TDLIB_API_HASH
    )
    
    if success:
        # Save to database
        db.add_account(user.id, phone, result)
        
        accounts_count = db.get_active_accounts_count(user.id)
        is_sudo = db.is_sudo(user.id) or user.id == OWNER_ID
        
        if is_sudo or accounts_count >= REQUIRED_IDS_COUNT:
            await msg.edit_text(
                f"✅ <b>Login Successful!</b>\n\n"
                f"📱 Total IDs linked: {accounts_count}\n"
                f"You can now use the reporting feature!",
                reply_markup=get_start_keyboard(user.id),
                parse_mode=ParseMode.HTML
            )
            context.user_data.clear()
            return ConversationHandler.END
        else:
            await msg.edit_text(
                f"✅ <b>Login Successful!</b>\n\n"
                f"📱 IDs linked: {accounts_count}/{REQUIRED_IDS_COUNT}\n\n"
                f"Send another phone number to add more IDs:",
                parse_mode=ParseMode.HTML
            )
            context.user_data["waiting_for"] = "phone"
            return WAITING_PHONE
    
    elif result == "2fa_required":
        context.user_data["waiting_for"] = "password"
        await msg.edit_text(
            "🔐 <b>2FA Required!</b>\n\nPlease enter your 2FA password:",
            parse_mode=ParseMode.HTML
        )
        return WAITING_PASSWORD
    
    else:
        await msg.edit_text(
            f"❌ <b>Error:</b> {result}\n\nPlease try again with /start",
            parse_mode=ParseMode.HTML
        )
        context.user_data.clear()
        return ConversationHandler.END


async def handle_password_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle 2FA password input"""
    user = update.effective_user
    phone = context.user_data.get("phone")
    phone_code_hash = context.user_data.get("phone_code_hash")
    
    msg = await update.message.reply_text(
        "🔐 <b>Verifying password...</b>",
        parse_mode=ParseMode.HTML
    )
    
    success, result = await tdlib_manager.verify_code(
        user.id, phone, "", phone_code_hash, TDLIB_API_ID, TDLIB_API_HASH, password=text
    )
    
    if success:
        db.add_account(user.id, phone, result)
        accounts_count = db.get_active_accounts_count(user.id)
        
        await msg.edit_text(
            f"✅ <b>Login Successful!</b>\n\n"
            f"📱 Total IDs linked: {accounts_count}",
            reply_markup=get_start_keyboard(user.id),
            parse_mode=ParseMode.HTML
        )
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await msg.edit_text(
            f"❌ <b>Error:</b> {result}\n\nPlease try again with /start",
            parse_mode=ParseMode.HTML
        )
        context.user_data.clear()
        return ConversationHandler.END


async def handle_add_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle add sudo user"""
    user = update.effective_user
    
    try:
        sudo_id = int(text)
        db.add_sudo(sudo_id, user.id)
        await update.message.reply_text(
            f"✅ <b>Added sudo user:</b> <code>{sudo_id}</code>",
            reply_markup=get_owner_keyboard(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error adding sudo: {e}")
        await update.message.reply_text(
            "❌ Invalid user ID!",
            reply_markup=get_owner_keyboard(),
            parse_mode=ParseMode.HTML
        )
    
    context.user_data.pop("waiting_for", None)


async def handle_remove_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle remove sudo user"""
    try:
        sudo_id = int(text)
        db.remove_sudo(sudo_id)
        await update.message.reply_text(
            f"✅ <b>Removed sudo user:</b> <code>{sudo_id}</code>",
            reply_markup=get_owner_keyboard(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error removing sudo: {e}")
        await update.message.reply_text(
            "❌ Invalid user ID!",
            reply_markup=get_owner_keyboard(),
            parse_mode=ParseMode.HTML
        )
    
    context.user_data.pop("waiting_for", None)


async def handle_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle group link input"""
    context.user_data["group_link"] = None if text.lower() == "skip" else text
    context.user_data["waiting_for"] = "target_link"
    
    await update.message.reply_text(
        "🎯 <b>Send Target Link</b>\n\n"
        "Send the link of user/channel/group you want to report:\n"
        "Example: @username or https://t.me/username",
        parse_mode=ParseMode.HTML
    )
    return WAITING_TARGET_LINK


async def handle_target_link(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle target link input"""
    # Verify target
    msg = await update.message.reply_text(
        "🔍 <b>Verifying target...</b>",
        parse_mode=ParseMode.HTML
    )
    
    # Store target
    context.user_data["target_link"] = text
    context.user_data["waiting_for"] = None
    
    await msg.edit_text(
        "✅ <b>Target Verified!</b>\n\nSelect report type:",
        reply_markup=get_report_types_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def handle_report_count(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle report count input"""
    try:
        count = int(text)
        if count < 1 or count > MAX_REPORTS_PER_BATCH:
            await update.message.reply_text(
                f"❌ Please enter a number between 1 and {MAX_REPORTS_PER_BATCH}",
                parse_mode=ParseMode.HTML
            )
            return WAITING_REPORT_COUNT
        
        context.user_data["report_count"] = count
        context.user_data["waiting_for"] = "description"
        
        await update.message.reply_text(
            "📝 <b>Report Description</b>\n\n"
            "Send a description for the report (or send 'skip' to skip):",
            parse_mode=ParseMode.HTML
        )
        return WAITING_DESCRIPTION
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid number!",
            parse_mode=ParseMode.HTML
        )
        return WAITING_REPORT_COUNT


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle description input and start reporting"""
    user = update.effective_user
    description = "" if text.lower() == "skip" else text
    
    # Generate report ID
    report_id = str(uuid.uuid4())[:8].upper()
    
    # Get all data
    group_link = context.user_data.get("group_link")
    target_link = context.user_data.get("target_link")
    report_type = context.user_data.get("report_type")
    report_count = context.user_data.get("report_count")
    
    # Save report to database
    db.add_report(report_id, user.id, target_link, report_type, report_count, description)
    db.increment_report_count(user.id)
    
    # Get user accounts
    accounts = db.get_user_accounts(user.id)
    
    # Send initial status
    status_msg = await update.message.reply_text(
        get_report_status_text(report_id, 0, 0, report_count),
        parse_mode=ParseMode.HTML
    )
    
    # Progress callback
    async def progress_callback(success, failed, total):
        try:
            await status_msg.edit_text(
                get_report_status_text(report_id, success, failed, total),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    
    # Start reporting
    success, result = await report_worker.start_reporting(
        report_id=report_id,
        user_id=user.id,
        accounts=accounts,
        target_link=target_link,
        join_link=group_link,
        report_type=report_type,
        report_count=report_count,
        description=description,
        progress_callback=progress_callback
    )
    
    if success:
        final_text = f"""
✅ <b>Reporting Completed!</b>

📊 <b>Report ID:</b> <code>{report_id}</code>
🎯 <b>Target:</b> {target_link}

📈 <b>Results:</b>
✅ Success: {result['success']}
❌ Failed: {result['failed']}
📊 Total: {result['success'] + result['failed']}

🎉 Thank you for using our service!
"""
    else:
        final_text = f"""
❌ <b>Reporting Failed!</b>

📊 <b>Report ID:</b> <code>{report_id}</code>
❌ <b>Error:</b> {result}

Please try again later.
"""
    
    await status_msg.edit_text(final_text, parse_mode=ParseMode.HTML)
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END


async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message"""
    user = update.effective_user
    message = update.message
    
    if user.id != OWNER_ID:
        return ConversationHandler.END
    
    users = db.get_all_users()
    sent = 0
    failed = 0
    
    status_msg = await message.reply_text("📢 Broadcasting...")
    
    for user_data in users:
        try:
            await message.copy(chat_id=user_data["user_id"])
            sent += 1
        except Exception:
            failed += 1
    
    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n📤 Sent: {sent}\n❌ Failed: {failed}",
        parse_mode=ParseMode.HTML
    )
    
    context.user_data.clear()
    return ConversationHandler.END


# ============= ERROR HANDLER =============

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


# ============= MAIN FUNCTION =============

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Conversation handler - FIXED for PTB v20+
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_callback, pattern="^(send_report|add_id|rtype_)"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_GROUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_TARGET_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_REPORT_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            WAITING_BROADCAST: [MessageHandler(filters.ALL, handle_broadcast)],
        },
        fallbacks=[CommandHandler("start", start_command)],
        per_message=True,  # FIXED: Enable per_message for callback queries
        per_chat=True,
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Bot started!")
    application.run_polling()


if __name__ == "__main__":
    main()
