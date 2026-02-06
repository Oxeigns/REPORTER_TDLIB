"""
TDLib Client Wrapper for Reporting Bot
Uses Telethon for Telegram API
"""
import asyncio
import os
import json
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, \
    InputReportReasonChildAbuse, InputReportReasonPornography, InputReportReasonCopyright, \
    InputReportReasonOther
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, \
    FloodWaitError, UserAlreadyParticipantError, ChatAdminRequiredError, \
    AuthKeyDuplicatedError, PhoneNumberInvalidError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TDLibManager:
    def __init__(self):
        self.clients = {}  # user_id -> {phone: client}
        self.sessions_dir = "sessions"
        self.active_auth_clients = {}  # For OTP flow
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, user_id, phone):
        """Get session file path"""
        clean_phone = "".join(filter(str.isdigit, phone))
        return os.path.join(self.sessions_dir, f"{user_id}_{clean_phone}")
    
    async def send_code(self, user_id, phone, api_id, api_hash):
        """Send OTP code"""
        session_path = self.get_session_path(user_id, phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            if await client.is_user_authorized():
                logger.info(f"User {user_id} with {phone} already authorized")
                await client.disconnect()
                return True, "already_authorized"
            
            # Send code
            sent = await client.send_code_request(phone)
            # Keep client in memory for verify_code
            self.active_auth_clients[phone] = client
            
            logger.info(f"Code sent to {phone} for user {user_id}")
            return True, sent.phone_code_hash
            
        except PhoneNumberInvalidError:
            await client.disconnect()
            logger.error(f"Invalid phone number: {phone}")
            return False, "Invalid phone number"
        except Exception as e:
            await client.disconnect()
            logger.error(f"Error sending code: {e}")
            return False, str(e)
    
    async def verify_code(self, user_id, phone, code, phone_code_hash, api_id, api_hash, password=None):
        """Verify OTP code and save session"""
        # Get client from active auth or create new
        client = self.active_auth_clients.get(phone)
        
        if not client:
            session_path = self.get_session_path(user_id, phone)
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
        
        try:
            # Check if already authorized
            if await client.is_user_authorized():
                logger.info(f"Already authorized for {phone}")
                session_string = client.session.save()
                await client.disconnect()
                if phone in self.active_auth_clients:
                    del self.active_auth_clients[phone]
                return True, session_string
            
            # Try to sign in with code
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    # Keep client for password entry
                    self.active_auth_clients[phone] = client
                    return False, "2fa_required"
            except PhoneCodeInvalidError:
                await client.disconnect()
                if phone in self.active_auth_clients:
                    del self.active_auth_clients[phone]
                return False, "invalid_code"
            
            # Successfully logged in - get session string
            session_string = client.session.save()
            
            # Store in memory
            if user_id not in self.clients:
                self.clients[user_id] = {}
            
            self.clients[user_id][phone] = {
                "client": client,
                "connected": True,
                "session_string": session_string
            }
            
            # Remove from active auth
            if phone in self.active_auth_clients:
                del self.active_auth_clients[phone]
            
            logger.info(f"Successfully logged in {phone} for user {user_id}")
            return True, session_string
            
        except Exception as e:
            await client.disconnect()
            if phone in self.active_auth_clients:
                del self.active_auth_clients[phone]
            logger.error(f"Error verifying code: {e}")
            return False, str(e)
    
    async def get_or_create_client(self, user_id, phone, api_id, api_hash):
        """Get existing client or create new one from saved session"""
        # Check if already connected in memory
        if user_id in self.clients and phone in self.clients[user_id]:
            client_info = self.clients[user_id][phone]
            client = client_info["client"]
            
            # Check if still connected
            if client.is_connected():
                try:
                    if await client.is_user_authorized():
                        logger.info(f"Using existing client for {phone}")
                        return client, True
                except Exception as e:
                    logger.warning(f"Existing client failed: {e}")
            
            # Try to reconnect
            try:
                await client.connect()
                if await client.is_user_authorized():
                    logger.info(f"Reconnected existing client for {phone}")
                    return client, True
            except Exception as e:
                logger.warning(f"Reconnection failed: {e}")
        
        # Create new client from file session
        session_path = self.get_session_path(user_id, phone)
        
        if not os.path.exists(f"{session_path}.session"):
            logger.error(f"Session file not found for {phone}")
            return None, False
        
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.error(f"Session not authorized for {phone}")
                await client.disconnect()
                return None, False
            
            # Store in memory
            if user_id not in self.clients:
                self.clients[user_id] = {}
            
            self.clients[user_id][phone] = {
                "client": client,
                "connected": True
            }
            
            logger.info(f"Loaded client from file for {phone}")
            return client, True
            
        except AuthKeyDuplicatedError:
            logger.error(f"Auth key duplicated for {phone}")
            await client.disconnect()
            return None, False
        except Exception as e:
            logger.error(f"Error creating client: {e}")
            await client.disconnect()
            return None, False
    
    async def get_report_target(self, client, link):
        """Get target entity and message IDs for reporting"""
        try:
            if "/" in link:
                username = link.split("/")[-1].replace("@", "").replace("+", "")
            else:
                username = link.replace("@", "")
            
            entity = await client.get_entity(username)
            
            # Get latest message ID
            async for msg in client.iter_messages(entity, limit=1):
                return entity, [msg.id]
            
            # Empty channel
            return entity, [0]
        except Exception as e:
            logger.error(f"Error getting entity for {link}: {e}")
            return None, None
    
    async def report_entity(self, client, target_link, reason_type, message=""):
        """Report an entity"""
        entity, msg_ids = await self.get_report_target(client, target_link)
        if not entity:
            return False, "Target not found"
        
        reason_map = {
            "SPAM": InputReportReasonSpam(),
            "VIOLENCE": InputReportReasonViolence(),
            "CHILD_ABUSE": InputReportReasonChildAbuse(),
            "PORNOGRAPHY": InputReportReasonPornography(),
            "COPYRIGHT": InputReportReasonCopyright(),
            "PERSONAL_DETAILS": InputReportReasonOther(),
            "ILLEGAL_DRUGS": InputReportReasonOther(),
            "FRAUD": InputReportReasonOther(),
        }
        
        reason = reason_map.get(reason_type.upper(), InputReportReasonSpam())
        
        try:
            result = await client(ReportRequest(
                peer=entity,
                id=msg_ids,
                reason=reason,
                message=message
            ))
            
            logger.info(f"Report sent successfully: {result}")
            return True, "Success"
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait: {e.seconds} seconds")
            return False, f"flood_wait:{e.seconds}"
        except Exception as e:
            logger.error(f"Error reporting: {e}")
            return False, str(e)
    
    async def join_chat(self, client, link):
        """Join a chat using link"""
        try:
            if "/" in link:
                if "joinchat" in link or "+" in link:
                    # Private link
                    hash_part = link.split("/")[-1].replace("+", "")
                    await client(ImportChatInviteRequest(hash_part))
                else:
                    # Public link
                    username = link.split("/")[-1]
                    entity = await client.get_entity(username)
                    await client(JoinChannelRequest(entity))
            else:
                # Username only
                entity = await client.get_entity(link)
                await client(JoinChannelRequest(entity))
            
            logger.info(f"Successfully joined {link}")
            return True, "joined"
            
        except UserAlreadyParticipantError:
            logger.info(f"Already member of {link}")
            return True, "already_member"
        except Exception as e:
            logger.error(f"Error joining chat: {e}")
            return False, str(e)
    
    async def disconnect_user(self, user_id):
        """Disconnect all clients for a user"""
        if user_id in self.clients:
            for phone, client_info in self.clients[user_id].items():
                try:
                    client = client_info["client"]
                    if client.is_connected():
                        await client.disconnect()
                        logger.info(f"Disconnected {phone} for user {user_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting {phone}: {e}")
            
            del self.clients[user_id]
    
    async def disconnect_all(self):
        """Disconnect all clients"""
        for user_id in list(self.clients.keys()):
            await self.disconnect_user(user_id)


class ReportWorker:
    """Worker class for handling reports"""
    
    def __init__(self, tdlib_manager, db):
        self.tdlib_manager = tdlib_manager
        self.db = db
        self.active_jobs = {}
    
    async def start_reporting(self, report_id, user_id, accounts, target_link, join_link, 
                              report_type, report_count, description, progress_callback):
        """Start reporting process"""
        self.active_jobs[report_id] = {
            "running": True,
            "success": 0,
            "failed": 0,
            "total": report_count
        }
        
        logger.info(f"Starting reporting job {report_id} for user {user_id}")
        logger.info(f"Target: {target_link}, Reports: {report_count}")
        
        if not accounts:
            logger.error("No accounts found")
            del self.active_jobs[report_id]
            return False, "No accounts found"
        
        # Connect all clients
        connected_clients = []
        for acc in accounts:
            phone = acc["phone"]
            api_id = acc.get("api_id")
            api_hash = acc.get("api_hash")
            
            if not api_id or not api_hash:
                logger.warning(f"Missing API credentials for {phone}")
                continue
            
            client, success = await self.tdlib_manager.get_or_create_client(
                user_id, phone, api_id, api_hash
            )
            
            if success and client:
                connected_clients.append({
                    "client": client,
                    "phone": phone
                })
            else:
                logger.warning(f"Failed to connect client for {phone}")
        
        if not connected_clients:
            logger.error("No valid accounts connected")
            del self.active_jobs[report_id]
            return False, "No valid accounts found - please re-login your IDs"
        
        logger.info(f"Connected {len(connected_clients)} clients for reporting")
        
        # Join target chat if needed
        if join_link and join_link.lower() != "skip":
            for client_info in connected_clients:
                try:
                    success, msg = await self.tdlib_manager.join_chat(
                        client_info["client"], join_link
                    )
                    if success:
                        logger.info(f"Joined {join_link}")
                        break
                except Exception as e:
                    logger.error(f"Error joining {join_link}: {e}")
                await asyncio.sleep(1)
        
        # Get target entity
        target_entity = None
        msg_ids = None
        for client_info in connected_clients:
            try:
                target_entity, msg_ids = await self.tdlib_manager.get_report_target(
                    client_info["client"], target_link
                )
                if target_entity:
                    logger.info(f"Got target entity: {target_entity}")
                    break
            except Exception as e:
                logger.error(f"Error getting entity: {e}")
        
        if not target_entity:
            logger.error("Could not get target entity")
            del self.active_jobs[report_id]
            return False, "Could not get target entity - check if link is valid"
        
        # Start reporting
        client_index = 0
        for i in range(report_count):
            if not self.active_jobs.get(report_id, {}).get("running", False):
                logger.info(f"Reporting job {report_id} stopped")
                break
            
            client_info = connected_clients[client_index % len(connected_clients)]
            client = client_info["client"]
            
            try:
                # Ensure client is still connected
                if not client.is_connected():
                    logger.warning(f"Client disconnected, reconnecting...")
                    await client.connect()
                
                success, result = await self.tdlib_manager.report_entity(
                    client, target_link, report_type, description
                )
                
                if success:
                    self.active_jobs[report_id]["success"] += 1
                    logger.info(f"Report {i+1}/{report_count} success")
                else:
                    self.active_jobs[report_id]["failed"] += 1
                    logger.warning(f"Report {i+1}/{report_count} failed: {result}")
                
                # Update progress
                await progress_callback(
                    self.active_jobs[report_id]["success"],
                    self.active_jobs[report_id]["failed"],
                    report_count
                )
                
            except Exception as e:
                self.active_jobs[report_id]["failed"] += 1
                logger.error(f"Report error: {e}")
            
            client_index += 1
            await asyncio.sleep(2)  # Delay between reports
        
        final_success = self.active_jobs[report_id]["success"]
        final_failed = self.active_jobs[report_id]["failed"]
        del self.active_jobs[report_id]
        
        logger.info(f"Reporting completed: {final_success} success, {final_failed} failed")
        
        return True, {"success": final_success, "failed": final_failed}
    
    def stop_reporting(self, report_id):
        """Stop active reporting job"""
        if report_id in self.active_jobs:
            self.active_jobs[report_id]["running"] = False
            logger.info(f"Stopped reporting job {report_id}")
            return True
        return False
