import asyncio
import os
import logging
from telethon import TelegramClient, functions, types, errors

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TelethonManager")

class TelethonManager:
    def __init__(self):
        self.sessions_dir = "sessions"
        # Phone number ko key bana kar client store karenge taaki OTP flow break na ho
        self.active_auth_clients = {} 
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def get_session_path(self, phone):
        clean_phone = "".join(filter(str.isdigit, phone))
        return os.path.join(self.sessions_dir, f"sess_{clean_phone}")

    # --- OTP FLOW FIX ---
    async def send_code(self, phone, api_id, api_hash):
        """OTP bhejta hai aur client instance ko memory mein rakhta hai"""
        session_path = self.get_session_path(phone)
        client = TelegramClient(session_path, api_id, api_hash)
        
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone)
            # Yahan client disconnect NAHI karna hai
            self.active_auth_clients[phone] = client
            return True, sent_code.phone_code_hash
        except Exception as e:
            logger.error(f"Error sending code to {phone}: {e}")
            await client.disconnect()
            return False, str(e)

    async def verify_code(self, phone, code, phone_code_hash, password=None):
        """Usi zinda client session se login complete karta hai"""
        client = self.active_auth_clients.get(phone)
        
        if not client:
            return False, "No active session found for this phone. Call send_code first."
        
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            return True, "Success"
        except errors.SessionPasswordNeededError:
            if password:
                await client.sign_in(password=password)
                return True, "Success with 2FA"
            return False, "2FA_REQUIRED"
        except Exception as e:
            logger.error(f"Verification error: {e}")
            return False, str(e)
        finally:
            # Login ke baad ya error ke baad cleanup
            await client.disconnect()
            if phone in self.active_auth_clients:
                del self.active_auth_clients[phone]

    # --- REPORTING LOGIC FIX ---
    async def get_target_and_msg_id(self, client, target_link):
        """Entity fetch karke uska latest message ID nikalta hai"""
        try:
            entity = await client.get_entity(target_link)
            # Message required hai report ke liye, isliye last message fetch kar rahe hain
            async for message in client.iter_messages(entity, limit=1):
                return entity, [message.id]
            
            # Agar koi message nahi mila, toh empty list (kam chances of success)
            return entity, []
        except Exception as e:
            logger.error(f"Failed to get target {target_link}: {e}")
            return None, None

    async def submit_report(self, client, target_link, reason_type, description):
        """Actual ReportRequest execution"""
        entity, msg_ids = await self.get_target_and_msg_id(client, target_link)
        
        if not entity or msg_ids is None:
            return False, "Target or Message ID not found"

        reason_map = {
            "SPAM": types.InputReportReasonSpam(),
            "VIOLENCE": types.InputReportReasonViolence(),
            "PORN": types.InputReportReasonPornography(),
            "CHILD_ABUSE": types.InputReportReasonChildAbuse(),
            "COPYRIGHT": types.InputReportReasonCopyright(),
            "FAKE": types.InputReportReasonFake(),
            "OTHER": types.InputReportReasonOther(),
        }

        try:
            # Note: id=[msg_id] is crucial for channels/users
            await client(functions.messages.ReportRequest(
                peer=entity,
                id=msg_ids, 
                reason=reason_map.get(reason_type.upper(), types.InputReportReasonSpam()),
                message=description
            ))
            return True, "Report Sent"
        except errors.FloodWaitError as e:
            return False, f"FloodWait: {e.seconds}s"
        except Exception as e:
            return False, str(e)

class ReportWorker:
    def __init__(self, manager: TelethonManager):
        self.manager = manager
        self.active_jobs = {}

    async def start_mass_report(self, report_id, accounts, target_link, report_type, description, progress_cb):
        """Saare accounts se ek ke baad ek report karna"""
        self.active_jobs[report_id] = True
        success_count = 0
        fail_count = 0

        for acc in accounts:
            if not self.active_jobs.get(report_id): break

            session_path = self.manager.get_session_path(acc['phone'])
            client = TelegramClient(session_path, acc['api_id'], acc['api_hash'])
            
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning(f"Account {acc['phone']} not authorized. Skipping.")
                    fail_count += 1
                    continue

                # Reporting
                ok, status = await self.manager.submit_report(client, target_link, report_type, description)
                
                if ok:
                    success_count += 1
                    logger.info(f"Report success from {acc['phone']}")
                else:
                    fail_count += 1
                    logger.error(f"Report failed from {acc['phone']}: {status}")

                # Update callback
                await progress_cb(success_count, fail_count)
                
                # Chota delay taaki account ban na ho
                await asyncio.sleep(1.5)

            except Exception as e:
                logger.error(f"Worker Error with {acc['phone']}: {e}")
                fail_count += 1
            finally:
                await client.disconnect()

        return success_count, fail_count

    def stop_job(self, report_id):
        self.active_jobs[report_id] = False
