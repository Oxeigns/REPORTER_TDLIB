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
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, \
    InputReportReasonChildAbuse, InputReportReasonPornography, InputReportReasonCopyright, \
    InputReportReasonOther
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, \
    FloodWaitError, UserAlreadyParticipantError, PhoneNumberInvalidError, \
    PhoneNumberUnoccupiedError, AuthKeyDuplicatedError, PhoneCodeExpiredError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TDLibManager:
    def __init__(self):
        self.sessions_dir = "sessions"
        # Store auth state: phone -> {client, phone_code_hash, api_id, api_hash, user_id, step}
        self.auth_state = {}
        # Store connected clients: user_id -> {phone -> client}
        self.user_clients = {}
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, user_id, phone):
        """Get session file path"""
        clean_phone = "".join(filter(str.isdigit, phone))
        return os.path.join(self.sessions_dir, f"user_{user_id}_{clean_phone}")
    
    async def send_code(self, user_id, phone, api_id, api_hash):
        """
        Step 1: Send OTP code
        Creates fresh session and sends code
        """
        # Clean any existing state for this phone
        await self._cleanup_phone(phone)
        
        session_path = self.get_session_path(user_id, phone)
        
        # Remove old session file if exists
        session_file = f"{session_path}.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info(f"Cleaned old session for {phone}")
            except Exception as e:
                logger.warning(f"Could not delete old session: {e}")
        
        # Create new client
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            # Check if somehow already authorized (rare case)
            if await client.is_user_authorized():
                me = await client.get_me()
                logger.info(f"Already logged in: {me.first_name}")
                # Store as valid session
                self._store_client(user_id, phone, client)
                return True, "already_authorized"
            
            # Send the code
            result = await client.send_code_request(phone)
            
            # Store auth state - IMPORTANT: Keep client connected!
            self.auth_state[phone] = {
                "client": client,
                "phone_code_hash": result.phone_code_hash,
                "api_id": api_id,
                "api_hash": api_hash,
                "user_id": user_id,
                "step": "code_sent",
                "session_path": session_path
            }
            
            logger.info(f"Code sent to {phone}, hash: {result.phone_code_hash}")
            return True, result.phone_code_hash
            
        except PhoneNumberInvalidError:
            await client.disconnect()
            return False, "Invalid phone number. Please use format: +919876543210"
        except PhoneNumberUnoccupiedError:
            await client.disconnect()
            return False, "This phone number is not registered on Telegram. Please create an account first."
        except FloodWaitError as e:
            await client.disconnect()
            return False, f"Too many attempts. Please wait {e.seconds} seconds."
        except Exception as e:
            await client.disconnect()
            logger.error(f"Send code error: {e}")
            error_str = str(e).lower()
            if "flood" in error_str:
                return False, "Too many attempts. Please try after some time."
            return False, f"Error sending code: {str(e)[:100]}"
    
    async def verify_code(self, user_id, phone, code, phone_code_hash=None, api_id=None, api_hash=None, password=None):
        """
        Step 2: Verify OTP code
        Uses the SAME client from send_code
        """
        state = self.auth_state.get(phone)
        
        if not state:
            return False, "Session expired. Please start again with /start"
        
        if state.get("step") not in ["code_sent", "2fa_needed"]:
            return False, "Invalid state. Please start again."
        
        # Get stored data
        client = state.get("client")
        stored_hash = state.get("phone_code_hash")
        api_id = state.get("api_id", api_id)
        api_hash = state.get("api_hash", api_hash)
        
        if not phone_code_hash:
            phone_code_hash = stored_hash
        
        if not client:
            return False, "Client disconnected. Please start again."
        
        try:
            # Ensure client is connected
            if not client.is_connected():
                await client.connect()
            
            # Attempt sign in
            try:
                if password and state.get("step") == "2fa_needed":
                    # 2FA step - sign in with password
                    await client.sign_in(password=password)
                else:
                    # Normal sign in with code
                    await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                
            except SessionPasswordNeededError:
                # Need 2FA password
                state["step"] = "2fa_needed"
                self.auth_state[phone] = state
                logger.info(f"2FA required for {phone}")
                return False, "2fa_required"
            
            except PhoneCodeInvalidError:
                return False, "Invalid code. Please check and try again."
            
            except PhoneCodeExpiredError:
                return False, "Code expired. Please request a new code."
            
            # SUCCESS! Verify authorization
            if not await client.is_user_authorized():
                return False, "Authorization failed. Please try again."
            
            # Get user info to confirm
            me = await client.get_me()
            if not me:
                return False, "Could not verify login. Please try again."
            
            logger.info(f"Successfully logged in: {me.first_name} (@{me.username})")
            
            # Store the connected client
            self._store_client(user_id, phone, client)
            
            # Clear auth state
            del self.auth_state[phone]
            
            return True, "success"
            
        except Exception as e:
            logger.error(f"Verify error: {e}")
            error_str = str(e).lower()
            if "password" in error_str and "invalid" in error_str:
                return False, "Invalid 2FA password."
            return False, f"Login failed: {str(e)[:100]}"
    
    def _store_client(self, user_id, phone, client):
        """Store connected client"""
        if user_id not in self.user_clients:
            self.user_clients[user_id] = {}
        self.user_clients[user_id][phone] = client
        logger.info(f"Stored client for {phone}")
    
    async def _cleanup_phone(self, phone):
        """Cleanup all state for a phone number"""
        # Clear auth state
        if phone in self.auth_state:
            old_client = self.auth_state[phone].get("client")
            if old_client:
                try:
                    await old_client.disconnect()
                except:
                    pass
            del self.auth_state[phone]
        
        # Clear from user_clients
        for user_id, phones in list(self.user_clients.items()):
            if phone in phones:
                old_client = phones[phone]
                try:
                    await old_client.disconnect()
                except:
                    pass
                del phones[phone]
                if not phones:
                    del self.user_clients[user_id]
    
    async def get_or_create_client(self, user_id, phone, api_id, api_hash):
        """
        Get existing client or create from saved session
        Returns (client, success)
        """
        # Check if already connected in memory
        if user_id in self.user_clients and phone in self.user_clients[user_id]:
            client = self.user_clients[user_id][phone]
            if client.is_connected():
                try:
                    if await client.is_user_authorized():
                        logger.info(f"Using existing client for {phone}")
                        return client, True
                except:
                    pass
        
        # Create from file
        session_path = self.get_session_path(user_id, phone)
        session_file = f"{session_path}.session"
        
        if not os.path.exists(session_file):
            logger.error(f"No session file for {phone}")
            return None, False
        
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            
            # Verify authorization
            if not await client.is_user_authorized():
                logger.error(f"Session not authorized for {phone}")
                await client.disconnect()
                # Delete bad session
                try:
                    os.remove(session_file)
                except:
                    pass
                return None, False
            
            # Verify by getting user info
            me = await client.get_me()
            if not me:
                raise Exception("No user data")
            
            # Store for reuse
            self._store_client(user_id, phone, client)
            logger.info(f"Loaded session for {me.first_name}")
            return client, True
            
        except AuthKeyDuplicatedError:
            logger.error(f"Auth key duplicated for {phone}")
            await client.disconnect()
            return None, False
        except Exception as e:
            logger.error(f"Load session error: {e}")
            await client.disconnect()
            # Delete bad session
            try:
                os.remove(session_file)
            except:
                pass
            return None, False
    
    async def get_report_target(self, client, link):
        """Get target entity"""
        try:
            # Parse link
            if "t.me/" in link:
                username = link.split("t.me/")[-1].split("/")[0].replace("@", "").replace("+", "")
            elif "/" in link:
                username = link.split("/")[-1].replace("@", "").replace("+", "")
            else:
                username = link.replace("@", "")
            
            entity = await client.get_entity(username)
            
            # Get latest message
            async for msg in client.iter_messages(entity, limit=1):
                return entity, [msg.id]
            
            return entity, [0]
        except Exception as e:
            logger.error(f"Entity error: {e}")
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
            await client(ReportRequest(
                peer=entity,
                id=msg_ids,
                reason=reason,
                message=message
            ))
            return True, "Success"
        except FloodWaitError as e:
            logger.warning(f"Flood wait: {e.seconds}s")
            return False, f"wait:{e.seconds}"
        except Exception as e:
            logger.error(f"Report error: {e}")
            return False, str(e)[:50]
    
    async def join_chat(self, client, link):
        """Join a chat"""
        try:
            if "t.me/+" in link or "joinchat" in link:
                # Private link
                hash_part = link.split("/")[-1].replace("+", "")
                await client(ImportChatInviteRequest(hash_part))
            elif "/" in link:
                # Public link
                username = link.split("/")[-1]
                entity = await client.get_entity(username)
                await client(JoinChannelRequest(entity))
            else:
                # Username
                entity = await client.get_entity(link)
                await client(JoinChannelRequest(entity))
            return True, "joined"
        except UserAlreadyParticipantError:
            return True, "already_member"
        except Exception as e:
            logger.error(f"Join error: {e}")
            return False, str(e)[:50]


class ReportWorker:
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
        
        logger.info(f"Starting report {report_id} for user {user_id}")
        
        if not accounts:
            del self.active_jobs[report_id]
            return False, "No accounts provided"
        
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
                connected_clients.append({"client": client, "phone": phone})
                logger.info(f"Connected: {phone}")
            else:
                logger.warning(f"Failed to connect: {phone}")
        
        if not connected_clients:
            del self.active_jobs[report_id]
            return False, "No valid sessions found. Please login again."
        
        logger.info(f"Total connected clients: {len(connected_clients)}")
        
        # Join chat if needed
        if join_link and join_link.lower() != "skip":
            for ci in connected_clients:
                try:
                    ok, _ = await self.tdlib_manager.join_chat(ci["client"], join_link)
                    if ok:
                        logger.info(f"Joined {join_link}")
                        break
                except Exception as e:
                    logger.error(f"Join error: {e}")
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
            except Exception as e:
                logger.error(f"Target error: {e}")
        
        if not target_entity:
            del self.active_jobs[report_id]
            return False, "Could not find target. Check the link."
        
        # Reporting loop
        idx = 0
        for i in range(report_count):
            if not self.active_jobs.get(report_id, {}).get("running"):
                logger.info("Job stopped")
                break
            
            ci = connected_clients[idx % len(connected_clients)]
            client = ci["client"]
            
            try:
                # Ensure connected
                if not client.is_connected():
                    await client.connect()
                
                success, result = await self.tdlib_manager.report_entity(
                    client, target_link, report_type, description
                )
                
                if success:
                    self.active_jobs[report_id]["success"] += 1
                else:
                    self.active_jobs[report_id]["failed"] += 1
                    if "wait:" in result:
                        # Flood wait, stop this client for now
                        pass
                
                await progress_callback(
                    self.active_jobs[report_id]["success"],
                    self.active_jobs[report_id]["failed"],
                    report_count
                )
                
            except Exception as e:
                self.active_jobs[report_id]["failed"] += 1
                logger.error(f"Report error: {e}")
            
            idx += 1
            await asyncio.sleep(2)  # Delay between reports
        
        result = {
            "success": self.active_jobs[report_id]["success"],
            "failed": self.active_jobs[report_id]["failed"]
        }
        del self.active_jobs[report_id]
        
        logger.info(f"Completed: {result}")
        return True, result
    
    def stop_reporting(self, report_id):
        """Stop a job"""
        if report_id in self.active_jobs:
            self.active_jobs[report_id]["running"] = False
            return True
        return False
