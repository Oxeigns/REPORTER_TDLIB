"""
TDLib Client Wrapper for Reporting Bot
Uses Telethon for Telegram API
"""
import asyncio
import os
import logging
from telethon import TelegramClient
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, \
    InputReportReasonChildAbuse, InputReportReasonPornography, InputReportReasonCopyright, \
    InputReportReasonOther
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, \
    FloodWaitError, UserAlreadyParticipantError, PhoneNumberInvalidError, \
    PhoneNumberUnoccupiedError, AuthKeyDuplicatedError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TDLibManager:
    def __init__(self):
        self.sessions_dir = "sessions"
        self.active_auth = {}  # phone -> auth data
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, user_id, phone):
        """Get session file path"""
        clean_phone = "".join(filter(str.isdigit, phone))
        return os.path.join(self.sessions_dir, f"{user_id}_{clean_phone}")
    
    async def send_code(self, user_id, phone, api_id, api_hash):
        """Send OTP code - ALWAYS create fresh client"""
        session_path = self.get_session_path(user_id, phone)
        
        # Clear any existing auth for this phone
        if phone in self.active_auth:
            old_client = self.active_auth[phone].get("client")
            if old_client:
                try:
                    await old_client.disconnect()
                except:
                    pass
            del self.active_auth[phone]
        
        # Delete old session file if exists (fresh start)
        session_file = f"{session_path}.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info(f"Deleted old session for {phone}")
            except:
                pass
        
        # Create fresh client
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            # Check if somehow already authorized (shouldn't happen after delete)
            if await client.is_user_authorized():
                logger.info(f"Already authorized: {phone}")
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
                "user_id": user_id,
                "code_sent": True
            }
            
            logger.info(f"Code sent to {phone}")
            return True, result.phone_code_hash
            
        except PhoneNumberInvalidError:
            await client.disconnect()
            return False, "Invalid phone number format"
        except PhoneNumberUnoccupiedError:
            await client.disconnect()
            return False, "This number is not registered on Telegram"
        except FloodWaitError as e:
            await client.disconnect()
            return False, f"Too many attempts. Wait {e.seconds} seconds"
        except Exception as e:
            await client.disconnect()
            logger.error(f"Send code error: {e}")
            return False, str(e)[:100]
    
    async def verify_code(self, user_id, phone, code, phone_code_hash, api_id, api_hash, password=None):
        """Verify OTP with PROPER validation"""
        auth_data = self.active_auth.get(phone)
        
        if not auth_data:
            return False, "Session expired. Please start again with /start"
        
        client = auth_data.get("client")
        stored_hash = auth_data.get("phone_code_hash")
        api_id = auth_data.get("api_id", api_id)
        api_hash = auth_data.get("api_hash", api_hash)
        
        if not phone_code_hash:
            phone_code_hash = stored_hash
        
        if not client or not client.is_connected():
            # Recreate client
            session_path = self.get_session_path(user_id, phone)
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
        
        try:
            # Try to sign in
            try:
                if password:
                    # 2FA flow
                    await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                else:
                    # Normal sign in
                    await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                
            except SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    # Update auth data for 2FA
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
                return False, "Invalid code. Please check and try again."
            
            # CRITICAL: Actually verify authorization
            is_authorized = await client.is_user_authorized()
            
            if not is_authorized:
                await client.disconnect()
                self._clear_auth(phone)
                logger.error(f"Authorization failed for {phone}")
                return False, "Login failed. Please try again."
            
            # Get user info to confirm
            try:
                me = await client.get_me()
                if not me:
                    raise Exception("Could not get user info")
                logger.info(f"Logged in as: {me.first_name} ({me.id})")
            except Exception as e:
                await client.disconnect()
                self._clear_auth(phone)
                logger.error(f"Failed to get user info: {e}")
                return False, "Login verification failed"
            
            # Success - save session
            session_string = client.session.save()
            
            # Keep client connected for reporting
            if user_id not in self.clients:
                self.clients = {}
            if user_id not in self.clients:
                self.clients[user_id] = {}
            
            self.clients[user_id] = {phone: {"client": client, "connected": True}}
            
            self._clear_auth(phone)
            
            return True, session_string
            
        except Exception as e:
            await client.disconnect()
            self._clear_auth(phone)
            logger.error(f"Verify error: {e}")
            return False, f"Error: {str(e)[:100]}"
    
    def _clear_auth(self, phone):
        """Clear auth data"""
        if phone in self.active_auth:
            del self.active_auth[phone]
    
    async def get_or_create_client(self, user_id, phone, api_id, api_hash):
        """Get client with VALID authorization check"""
        session_path = self.get_session_path(user_id, phone)
        session_file = f"{session_path}.session"
        
        # Check if session file exists
        if not os.path.exists(session_file):
            logger.error(f"No session file for {phone}")
            return None, False
        
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            # CRITICAL: Verify actually authorized
            if not await client.is_user_authorized():
                logger.error(f"Session not authorized for {phone}")
                await client.disconnect()
                # Delete invalid session
                try:
                    os.remove(session_file)
                except:
                    pass
                return None, False
            
            # Verify by getting user info
            try:
                me = await client.get_me()
                if not me:
                    raise Exception("No user data")
                logger.info(f"Valid session for {me.first_name}")
            except Exception as e:
                logger.error(f"Invalid session data: {e}")
                await client.disconnect()
                try:
                    os.remove(session_file)
                except:
                    pass
                return None, False
            
            return client, True
            
        except AuthKeyDuplicatedError:
            logger.error(f"Auth key duplicated")
            await client.disconnect()
            return None, False
        except Exception as e:
            logger.error(f"Client error: {e}")
            await client.disconnect()
            return None, False
    
    async def get_report_target(self, client, link):
        """Get target entity"""
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
            logger.error(f"Entity error: {e}")
            return None, None
    
    async def report_entity(self, client, target_link, reason_type, message=""):
        """Report entity"""
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
            await client(ReportRequest(
                peer=entity,
                id=msg_ids,
                reason=reason,
                message=message
            ))
            return True, "Success"
        except FloodWaitError as e:
            return False, f"flood:{e.seconds}"
        except Exception as e:
            logger.error(f"Report error: {e}")
            return False, str(e)[:50]
    
    async def join_chat(self, client, link):
        """Join chat"""
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
            return False, str(e)[:50]


class ReportWorker:
    def __init__(self, tdlib_manager, db):
        self.tdlib_manager = tdlib_manager
        self.db = db
        self.active_jobs = {}
    
    async def start_reporting(self, report_id, user_id, accounts, target_link, join_link, 
                              report_type, report_count, description, progress_callback):
        """Start reporting with proper validation"""
        self.active_jobs[report_id] = {
            "running": True, "success": 0, "failed": 0, "total": report_count
        }
        
        if not accounts:
            del self.active_jobs[report_id]
            return False, "No accounts found"
        
        # Connect and VALIDATE each client
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
                connected_clients.append({"client": client, "phone": phone})
                logger.info(f"Connected: {phone}")
            else:
                logger.warning(f"Failed to connect: {phone}")
        
        if not connected_clients:
            del self.active_jobs[report_id]
            return False, "No valid sessions. Please re-login your accounts."
        
        # Join chat if needed
        if join_link and join_link.lower() != "skip":
            for ci in connected_clients:
                try:
                    ok, _ = await self.tdlib_manager.join_chat(ci["client"], join_link)
                    if ok:
                        break
                except:
                    pass
                await asyncio.sleep(1)
        
        # Get target
        target_entity = None
        for ci in connected_clients:
            try:
                target_entity, _ = await self.tdlib_manager.get_report_target(
                    ci["client"], target_link
                )
                if target_entity:
                    break
            except:
                pass
        
        if not target_entity:
            del self.active_jobs[report_id]
            return False, "Invalid target link"
        
        # Report loop
        idx = 0
        for i in range(report_count):
            if not self.active_jobs.get(report_id, {}).get("running"):
                break
            
            ci = connected_clients[idx % len(connected_clients)]
            client = ci["client"]
            
            try:
                if not client.is_connected():
                    await client.connect()
                
                ok, _ = await self.tdlib_manager.report_entity(
                    client, target_link, report_type, description
                )
                
                if ok:
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
                logger.error(f"Report error: {e}")
            
            idx += 1
            await asyncio.sleep(2)
        
        result = {
            "success": self.active_jobs[report_id]["success"],
            "failed": self.active_jobs[report_id]["failed"]
        }
        del self.active_jobs[report_id]
        
        return True, result
