import asyncio
import os
import logging
from telethon import TelegramClient, functions, types, errors

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TDLibManager:
    def __init__(self):
        self.sessions_dir = "sessions"
        # OTP flow ko track karne ke liye active clients ko memory mein rakhte hain
        self.active_auth_clients = {} 
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, user_id, phone):
        """Heroku/Local file system ke liye clean path"""
        clean_phone = "".join(filter(str.isdigit, phone))
        return os.path.join(self.sessions_dir, f"{user_id}_{clean_phone}")

    # --- FIX 1: Stateful OTP Flow ---
    async def send_code(self, user_id, phone, api_id, api_hash):
        """OTP bhejta hai aur client instance ko verify_code ke liye zinda rakhta hai"""
        session_path = self.get_session_path(user_id, phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            # Yahan disconnect nahi karna, warna sign_in fail ho jayega
            self.active_auth_clients[phone] = client 
            return True, sent.phone_code_hash
        except Exception as e:
            logger.error(f"Error sending code to {phone}: {e}")
            await client.disconnect()
            return False, str(e)

    async def verify_code(self, user_id, phone, code, phone_code_hash, api_id, api_hash, password=None):
        """Usi client instance se login complete karta hai"""
        client = self.active_auth_clients.get(phone)
        
        # Agar client memory mein nahi hai (restart case), toh naya connect karo
        if not client:
            session_path = self.get_session_path(user_id, phone)
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()

        try:
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            except errors.SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    return False, "2fa_required"
            
            return True, "success"
        except Exception as e:
            logger.error(f"Error verifying code for {phone}: {e}")
            return False, str(e)
        finally:
            # Kaam khatam, ab disconnect aur cleanup
            await client.disconnect()
            if phone in self.active_auth_clients:
                del self.active_auth_clients[phone]

    # --- FIX 2: Message-ID Based Reporting ---
    async def get_report_target(self, client, link):
        """Target fetch karke latest message ID nikalta hai (Required for Reports)"""
        try:
            entity = await client.get_entity(link)
            # Latest message uthana zaroori hai reporting ke liye
            async for msg in client.iter_messages(entity, limit=1):
                return entity, [msg.id]
            # Agar channel khali hai toh empty list (kam success rate)
            return entity, [0]
        except Exception as e:
            logger.error(f"Entity error for {link}: {e}")
            return None, None

    async def report_entity(self, client, target_link, reason_type, message=""):
        """Proper API call with target entity and message ID"""
        entity, msg_ids = await self.get_report_target(client, target_link)
        if not entity:
            return False, "Target not found"

        reason_map = {
            "SPAM": types.InputReportReasonSpam(),
            "VIOLENCE": types.InputReportReasonViolence(),
            "PORNOGRAPHY": types.InputReportReasonPornography(),
            "CHILD_ABUSE": types.InputReportReasonChildAbuse(),
            "COPYRIGHT": types.InputReportReasonCopyright(),
            "OTHER": types.InputReportReasonOther(),
        }
        
        reason = reason_map.get(reason_type.upper(), types.InputReportReasonSpam())

        try:
            # Corrected: id parameter real message ID list mangta hai
            await client(functions.messages.ReportRequest(
                peer=entity,
                id=msg_ids,
                reason=reason,
                message=message
            ))
            return True, "Success"
        except errors.FloodWaitError as e:
            return False, f"flood_wait:{e.seconds}"
        except Exception as e:
            logger.error(f"Reporting error: {e}")
            return False, str(e)

class ReportWorker:
    def __init__(self, tdlib_manager, db):
        self.tdlib_manager = tdlib_manager
        self.db = db
        self.active_jobs = {}

    async def start_reporting(self, report_id, user_id, accounts, target_link, join_link, 
                              report_type, report_count, description, progress_callback):
        """Main Loop jo mass reporting chalayega"""
        self.active_jobs[report_id] = {"running": True, "success": 0, "failed": 0}
        
        # Saare authorized accounts ko connect karna
        clients = []
        for acc in accounts:
            session_path = self.tdlib_manager.get_session_path(user_id, acc['phone'])
            client = TelegramClient(session_path, acc['api_id'], acc['api_hash'])
            try:
                await client.connect()
                if await client.is_user_authorized():
                    clients.append(client)
                else:
                    await client.disconnect()
            except:
                continue

        if not clients:
            return False, "No authorized accounts found."

        try:
            for i in range(report_count):
                if not self.active_jobs.get(report_id, {}).get("running"):
                    break
                
                # Round-robin distribution of reports among accounts
                current_client = clients[i % len(clients)]
                
                success, res = await self.tdlib_manager.report_entity(
                    current_client, target_link, report_type, description
                )
                
                if success:
                    self.active_jobs[report_id]["success"] += 1
                else:
                    self.active_jobs[report_id]["failed"] += 1
                
                # Bot UI par progress update bhejna
                await progress_callback(
                    self.active_jobs[report_id]["success"], 
                    self.active_jobs[report_id]["failed"], 
                    report_count
                )
                
                # Telegram anti-spam ke liye sleep
                await asyncio.sleep(2)

            return True, "Process Completed"
        finally:
            # Cleanup: Saare sessions close karo
            for c in clients:
                try: await c.disconnect()
                except: pass
            if report_id in self.active_jobs:
                del self.active_jobs[report_id]
