"""
TDLib Client Wrapper for Reporting Bot
Uses python-telegram (tdlib wrapper)
"""
import asyncio
import os
import json
import logging
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, \
    InputReportReasonChildAbuse, InputReportReasonPornography, InputReportReasonCopyright, \
    InputReportReasonOther
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, \
    FloodWaitError, UserAlreadyParticipantError, ChatAdminRequiredError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TDLibManager:
    def __init__(self):
        self.clients = {}  # user_id -> list of clients
        self.sessions_dir = "sessions"
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, user_id, phone):
        """Get session file path"""
        return os.path.join(self.sessions_dir, f"{user_id}_{phone.replace('+', '')}")
    
    async def create_client(self, user_id, phone, api_id, api_hash):
        """Create new Telegram client"""
        session_path = self.get_session_path(user_id, phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None, "not_authorized"
            
            # Add to clients dict
            if user_id not in self.clients:
                self.clients[user_id] = []
            self.clients[user_id].append({
                "client": client,
                "phone": phone,
                "connected": True
            })
            
            return client, "success"
        except Exception as e:
            logger.error(f"Error creating client: {e}")
            try:
                await client.disconnect()
            except:
                pass
            return None, str(e)
    
    async def send_code(self, user_id, phone, api_id, api_hash):
        """Send OTP code"""
        session_path = self.get_session_path(user_id, phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
            await client.disconnect()
            return True, sent.phone_code_hash
        except Exception as e:
            logger.error(f"Error sending code: {e}")
            try:
                await client.disconnect()
            except:
                pass
            return False, str(e)
    
    async def verify_code(self, user_id, phone, code, phone_code_hash, api_id, api_hash, password=None):
        """Verify OTP code"""
        session_path = self.get_session_path(user_id, phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        try:
            await client.connect()
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    await client.disconnect()
                    return False, "2fa_required"
            except PhoneCodeInvalidError:
                await client.disconnect()
                return False, "invalid_code"
            
            # Get session string
            session_string = client.session.save()
            await client.disconnect()
            
            return True, session_string
        except Exception as e:
            logger.error(f"Error verifying code: {e}")
            try:
                await client.disconnect()
            except:
                pass
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
            return True, "joined"
        except UserAlreadyParticipantError:
            return True, "already_member"
        except Exception as e:
            logger.error(f"Error joining chat: {e}")
            return False, str(e)
    
    async def get_entity(self, client, link):
        """Get entity from link/username"""
        try:
            if "/" in link:
                username = link.split("/")[-1].replace("@", "")
            else:
                username = link.replace("@", "")
            entity = await client.get_entity(username)
            return entity
        except Exception as e:
            logger.error(f"Error getting entity: {e}")
            return None
    
    async def report_entity(self, client, entity, reason_type, message=""):
        """Report an entity"""
        try:
            # Map reason type to InputReportReason
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
            
            reason = reason_map.get(reason_type, InputReportReasonSpam())
            
            result = await client(ReportRequest(
                peer=entity,
                id=[0],  # For user/channel reports
                reason=reason,
                message=message
            ))
            
            return True, result
        except FloodWaitError as e:
            logger.warning(f"Flood wait: {e.seconds} seconds")
            return False, f"flood_wait:{e.seconds}"
        except Exception as e:
            logger.error(f"Error reporting: {e}")
            return False, str(e)
    
    async def disconnect_user(self, user_id):
        """Disconnect all clients for a user"""
        if user_id in self.clients:
            for client_info in self.clients[user_id]:
                try:
                    await client_info["client"].disconnect()
                except:
                    pass
            del self.clients[user_id]
    
    def get_connected_clients(self, user_id):
        """Get all connected clients for user"""
        return self.clients.get(user_id, [])


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
        
        # Load clients
        clients = []
        for account in accounts:
            session_path = self.tdlib_manager.get_session_path(user_id, account["phone"])
            if os.path.exists(f"{session_path}.session"):
                client = TelegramClient(session_path, account.get("api_id", 0), account.get("api_hash", ""))
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        clients.append(client)
                except:
                    pass
        
        if not clients:
            return False, "No valid accounts found"
        
        # Join target chat if needed
        target_entity = None
        if join_link and join_link != target_link:
            for client in clients:
                success, msg = await self.tdlib_manager.join_chat(client, join_link)
                if success:
                    break
                await asyncio.sleep(1)
        
        # Get target entity
        for client in clients:
            target_entity = await self.tdlib_manager.get_entity(client, target_link)
            if target_entity:
                break
        
        if not target_entity:
            # Cleanup
            for client in clients:
                try:
                    await client.disconnect()
                except:
                    pass
            return False, "Could not get target entity"
        
        # Start reporting
        client_index = 0
        for i in range(report_count):
            if not self.active_jobs.get(report_id, {}).get("running", False):
                break
            
            client = clients[client_index % len(clients)]
            
            try:
                success, result = await self.tdlib_manager.report_entity(
                    client, target_entity, report_type, description
                )
                
                if success:
                    self.active_jobs[report_id]["success"] += 1
                else:
                    self.active_jobs[report_id]["failed"] += 1
                    if "flood_wait" in str(result):
                        # Skip this client for now
                        pass
                
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
            await asyncio.sleep(1.5)  # Delay between reports
        
        # Cleanup
        for client in clients:
            try:
                await client.disconnect()
            except:
                pass
        
        final_success = self.active_jobs[report_id]["success"]
        final_failed = self.active_jobs[report_id]["failed"]
        del self.active_jobs[report_id]
        
        return True, {"success": final_success, "failed": final_failed}
    
    def stop_reporting(self, report_id):
        """Stop active reporting job"""
        if report_id in self.active_jobs:
            self.active_jobs[report_id]["running"] = False
            return True
        return False
