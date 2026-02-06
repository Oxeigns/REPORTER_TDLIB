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
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, \
    InputReportReasonChildAbuse, InputReportReasonPornography, InputReportReasonCopyright, \
    InputReportReasonOther
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, \
    FloodWaitError, UserAlreadyParticipantError, ChatAdminRequiredError, \
    AuthKeyDuplicatedError, PhoneNumberInvalidError, PhoneCodeExpiredError, \
    PhoneNumberUnoccupiedError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TDLibManager:
    def __init__(self):
        self.clients = {}  # user_id -> {phone: client}
        self.sessions_dir = "sessions"
        self.active_auth = {}  # phone -> {client, phone_code_hash, api_id, api_hash, user_id}
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
            
            # Check if already authorized
            if await client.is_user_authorized():
                logger.info(f"User {user_id} with {phone} already authorized")
                await client.disconnect()
                return True, "already_authorized"
            
            # Send code
            result = await client.send_code_request(phone)
            
            # Store auth data
            self.active_auth[phone] = {
                "client": client,
                "phone_code_hash": result.phone_code_hash,
                "api_id": api_id,
                "api_hash": api_hash,
                "user_id": user_id
            }
            
            logger.info(f"Code sent to {phone} for user {user_id}")
            return True, result.phone_code_hash
            
        except PhoneNumberInvalidError:
            await client.disconnect()
            logger.error(f"Invalid phone number: {phone}")
            return False, "Invalid phone number"
        except PhoneNumberUnoccupiedError:
            await client.disconnect()
            logger.error(f"Phone number not registered on Telegram: {phone}")
            return False, "This phone number is not registered on Telegram. Please create a Telegram account first."
        except FloodWaitError as e:
            await client.disconnect()
            logger.error(f"Flood wait: {e.seconds} seconds")
            return False, f"Too many attempts. Please wait {e.seconds} seconds."
        except Exception as e:
            await client.disconnect()
            error_msg = str(e).lower()
            if "resend" in error_msg or "all available options" in error_msg:
                logger.error(f"Code resend limit for {phone}: {e}")
                return False, "code_resend_limit"
            logger.error(f"Error sending code: {e}")
            return False, str(e)
    
    async def resend_code(self, phone):
        """Resend the code"""
        auth_data = self.active_auth.get(phone)
        if not auth_data:
            return False, "No active login session. Please start again."
        
        client = auth_data.get("client")
        phone_code_hash = auth_data.get("phone_code_hash")
        
        if not client or not client.is_connected():
            return False, "Session expired. Please start again."
        
        try:
            # Try to resend code using Telethon's resend method
            result = await client(ResendCodeRequest(phone, phone_code_hash))
            
            # Update stored hash
            auth_data["phone_code_hash"] = result.phone_code_hash
            
            logger.info(f"Code resent to {phone}")
            return True, result.phone_code_hash
            
        except FloodWaitError as e:
            logger.error(f"Flood wait on resend: {e.seconds}")
            return False, f"Please wait {e.seconds} seconds before requesting again."
        except Exception as e:
            logger.error(f"Error resending code: {e}")
            error_msg = str(e).lower()
            if "resend" in error_msg or "all available options" in error_msg:
                return False, "code_resend_limit"
            return False, str(e)
    
    async def verify_code(self, user_id, phone, code, phone_code_hash, api_id, api_hash, password=None):
        """Verify OTP code and save session"""
        auth_data = self.active_auth.get(phone)
        client = None
        
        if auth_data:
            client = auth_data.get("client")
            # Use stored values if not provided
            if not phone_code_hash:
                phone_code_hash = auth_data.get("phone_code_hash")
            api_id = auth_data.get("api_id", api_id)
            api_hash = auth_data.get("api_hash", api_hash)
        
        # Create fresh client if needed (for 2FA or if no active auth)
        if not client or password:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            
            session_path = self.get_session_path(user_id, phone)
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
        
        try:
            # Check if already authorized
            if await client.is_user_authorized():
                logger.info(f"Already authorized for {phone}")
                session_string = client.session.save()
                await client.disconnect()
                self._clear_auth(phone)
                return True, session_string
            
            # Sign in
            try:
                if password:
                    # 2FA flow
                    try:
                        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                    except SessionPasswordNeededError:
                        await client.sign_in(password=password)
                else:
                    # Normal flow
                    await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                    
            except SessionPasswordNeededError:
                # Need 2FA password
                self._clear_auth(phone)
                self.active_auth[phone] = {
                    "client": client,
                    "phone_code_hash": phone_code_hash,
                    "api_id": api_id,
                    "api_hash": api_hash,
                    "user_id": user_id
                }
                return False, "2fa_required"
                
            except PhoneCodeInvalidError:
                await client.disconnect()
                self._clear_auth(phone)
                return False, "invalid_code"
                
            except PhoneCodeExpiredError:
                await client.disconnect()
                self._clear_auth(phone)
                return False, "Code expired. Please request a new code."
            
            # Success - save session
            session_string = client.session.save()
            
            # Store in clients dict
            if user_id not in self.clients:
                self.clients[user_id] = {}
            
            self.clients[user_id][phone] = {
                "client": client,
                "connected": True,
                "session_string": session_string
            }
            
            self._clear_auth(phone)
            
            logger.info(f"Successfully logged in {phone} for user {user_id}")
            return True, session_string
            
        except Exception as e:
            await client.disconnect()
            self._clear_auth(phone)
            error_msg = str(e).lower()
            if "resend" in error_msg or "all available options" in error_msg:
                logger.error(f"Resend limit hit for {phone}: {e}")
                return False, "code_resend_limit"
            logger.error(f"Error verifying code: {e}")
            return False, str(e)
    
    def _clear_auth(self, phone):
        """Clear auth data for a phone number"""
        if phone in self.active_auth:
            del self.active_auth[phone]
    
    async def get_or_create_client(self, user_id, phone, api_id, api_hash):
        """Get existing client or create new one from saved session"""
        # Check memory first
        if user_id in self.clients and phone in self.clients[user_id]:
            client_info = self.clients[user_id][phone]
            client = client_info["client"]
            
            if client.is_connected():
                try:
                    if await client.is_user_authorized():
                        return client, True
                except:
                    pass
            
            # Try reconnect
            try:
                await client.connect()
                if await client.is_user_authorized():
                    return client, True
            except:
                pass
        
        # Create from file
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
            
            if user_id not in self.clients:
                self.clients[user_id] = {}
            
            self.clients[user_id][phone] = {
                "client": client,
                "connected": True
            }
            
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
        """Get target entity and message IDs"""
        try:
            if "/" in link:
                username = link.split("/")[-1].replace("@", "").replace("+", "")
            else:
                username = link.replace("@", "")
            
            entity = await client.get_entity(username)
            
            async for msg in client.iter_messages(entity, limit=1):
                return entity, [msg.id]
            
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
            
            return True, "Success"
            
        except FloodWaitError as e:
            return False, f"flood_wait:{e.seconds}"
        except Exception as e:
            logger.error(f"Error reporting: {e}")
            return False, str(e)
    
    async def join_chat(self, client, link):
        """Join a chat"""
        try:
            if "/" in link:
                if "joinchat" in link or "+" in link:
                    hash_part = link.split("/")[-1].replace("+", "")
                    await client(ImportChatInviteRequest(hash_part))
                else:
                    username = link.split("/")[-1]
                    entity = await client.get_entity(username)
                    await client(JoinChannelRequest(entity))
            else:
                entity = await client.get_entity(link)
                await client(JoinChannelRequest(entity))
            
            return True, "joined"
            
        except UserAlreadyParticipantError:
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
                except:
                    pass
            del self.clients[user_id]


class ReportWorker:
    """Worker class for handling reports"""
    
    def __init__(self, tdlib_manager, db):
        self.tdlib_manager = tdlib_manager
        self.db = db
        self.active_jobs = {}
    
    async def start_reporting(self, report_id, user_id, accounts, target_link, join_link, 
                              report_type, report_count, description, progress_callback):
        """Start reporting"""
        self.active_jobs[report_id] = {
            "running": True,
            "success": 0,
            "failed": 0,
            "total": report_count
        }
        
        if not accounts:
            del self.active_jobs[report_id]
            return False, "No accounts found"
        
        # Connect clients
        connected_clients = []
        for acc in accounts:
            phone = acc["phone"]
            api_id = acc.get("api_id")
            api_hash = acc.get("api_hash")
            
            if not api_id or not api_hash:
                continue
            
            client, success = await self.tdlib_manager.get_or_create_client(
                user_id, phone, api_id, api_hash
            )
            
            if success and client:
                connected_clients.append({
                    "client": client,
                    "phone": phone
                })
        
        if not connected_clients:
            del self.active_jobs[report_id]
            return False, "No valid accounts found - please re-login your IDs"
        
        # Join chat if needed
        if join_link and join_link.lower() != "skip":
            for client_info in connected_clients:
                try:
                    success, _ = await self.tdlib_manager.join_chat(
                        client_info["client"], join_link
                    )
                    if success:
                        break
                except:
                    pass
                await asyncio.sleep(1)
        
        # Get target
        target_entity = None
        for client_info in connected_clients:
            try:
                target_entity, _ = await self.tdlib_manager.get_report_target(
                    client_info["client"], target_link
                )
                if target_entity:
                    break
            except:
                pass
        
        if not target_entity:
            del self.active_jobs[report_id]
            return False, "Could not get target - check if link is valid"
        
        # Report
        client_index = 0
        for i in range(report_count):
            if not self.active_jobs.get(report_id, {}).get("running", False):
                break
            
            client_info = connected_clients[client_index % len(connected_clients)]
            client = client_info["client"]
            
            try:
                if not client.is_connected():
                    await client.connect()
                
                success, _ = await self.tdlib_manager.report_entity(
                    client, target_link, report_type, description
                )
                
                if success:
                    self.active_jobs[report_id]["success"] += 1
                else:
                    self.active_jobs[report_id]["failed"] += 1
                
                await progress_callback(
                    self.active_jobs[report_id]["success"],
                    self.active_jobs[report_id]["failed"],
                    report_count
                )
                
            except Exception as e:
                self.active_jobs[report_id]["failed"] += 1
            
            client_index += 1
            await asyncio.sleep(2)
        
        final_success = self.active_jobs[report_id]["success"]
        final_failed = self.active_jobs[report_id]["failed"]
        del self.active_jobs[report_id]
        
        return True, {"success": final_success, "failed": final_failed}
