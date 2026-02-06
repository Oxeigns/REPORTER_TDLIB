"""
Database Handler for Reporting Bot
"""
from pymongo import MongoClient, ASCENDING
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, uri, db_name):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.users = self.db["users"]
        self.sudos = self.db["sudos"]
        self.accounts = self.db["accounts"]
        self.reports = self.db["reports"]
        self.sessions = self.db["sessions"]
        
        # Create indexes
        self.users.create_index("user_id", unique=True)
        self.sudos.create_index("user_id", unique=True)
        self.accounts.create_index([("user_id", ASCENDING), ("phone", ASCENDING)])
        self.reports.create_index("report_id")
        
        logger.info("Database initialized")
    
    # User Management
    def add_user(self, user_id, username=None, first_name=None):
        """Add new user to database"""
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_date": datetime.now(),
                "is_banned": False,
                "report_count": 0
            }
            self.users.update_one(
                {"user_id": user_id},
                {"$setOnInsert": user_data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id):
        """Get user data"""
        return self.users.find_one({"user_id": user_id})
    
    def get_all_users(self):
        """Get all users"""
        return list(self.users.find())
    
    def update_user(self, user_id, data):
        """Update user data"""
        return self.users.update_one(
            {"user_id": user_id},
            {"$set": data}
        )
    
    def increment_report_count(self, user_id):
        """Increment user report count"""
        return self.users.update_one(
            {"user_id": user_id},
            {"$inc": {"report_count": 1}}
        )
    
    # Sudo Management
    def add_sudo(self, user_id, added_by):
        """Add sudo user"""
        try:
            sudo_data = {
                "user_id": user_id,
                "added_by": added_by,
                "added_date": datetime.now()
            }
            self.sudos.update_one(
                {"user_id": user_id},
                {"$set": sudo_data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding sudo: {e}")
            return False
    
    def remove_sudo(self, user_id):
        """Remove sudo user"""
        result = self.sudos.delete_one({"user_id": user_id})
        return result.deleted_count > 0
    
    def is_sudo(self, user_id):
        """Check if user is sudo"""
        return self.sudos.find_one({"user_id": user_id}) is not None
    
    def get_all_sudos(self):
        """Get all sudo users"""
        return list(self.sudos.find())
    
    # Account Management (Telegram IDs)
    def add_account(self, user_id, phone, session_string=None, api_id=None, api_hash=None, is_active=True):
        """Add Telegram account for user"""
        try:
            account_data = {
                "user_id": user_id,
                "phone": phone,
                "session_string": session_string,
                "api_id": api_id,
                "api_hash": api_hash,
                "is_active": is_active,
                "added_date": datetime.now(),
                "last_used": None
            }
            self.accounts.update_one(
                {"user_id": user_id, "phone": phone},
                {"$set": account_data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding account: {e}")
            return False
    
    def get_user_accounts(self, user_id):
        """Get all accounts for a user"""
        return list(self.accounts.find({"user_id": user_id, "is_active": True}))
    
    def get_active_accounts_count(self, user_id):
        """Get count of active accounts"""
        return self.accounts.count_documents({"user_id": user_id, "is_active": True})
    
    def update_account_session(self, user_id, phone, session_string):
        """Update account session"""
        return self.accounts.update_one(
            {"user_id": user_id, "phone": phone},
            {"$set": {"session_string": session_string}}
        )
    
    def remove_account(self, user_id, phone):
        """Remove account"""
        return self.accounts.delete_one({"user_id": user_id, "phone": phone})
    
    def remove_all_accounts(self, user_id):
        """Remove all accounts for user"""
        return self.accounts.delete_many({"user_id": user_id})
    
    # Report Management
    def add_report(self, report_id, user_id, target, report_type, count, description):
        """Add report log"""
        try:
            report_data = {
                "report_id": report_id,
                "user_id": user_id,
                "target": target,
                "report_type": report_type,
                "requested_count": count,
                "description": description,
                "success_count": 0,
                "fail_count": 0,
                "status": "running",
                "created_at": datetime.now(),
                "completed_at": None
            }
            self.reports.insert_one(report_data)
            return True
        except Exception as e:
            logger.error(f"Error adding report: {e}")
            return False
    
    def update_report_status(self, report_id, success=0, fail=0, status=None):
        """Update report status"""
        update_data = {}
        if success:
            update_data["$inc"] = {"success_count": success}
        if fail:
            update_data["$inc"] = {"fail_count": fail}
        if status:
            update_data["$set"] = {"status": status}
            if status == "completed":
                update_data["$set"]["completed_at"] = datetime.now()
        
        return self.reports.update_one({"report_id": report_id}, update_data)
    
    def get_report(self, report_id):
        """Get report by ID"""
        return self.reports.find_one({"report_id": report_id})
    
    # Session Management (for temporary data)
    def set_session(self, user_id, key, value):
        """Set temporary session data"""
        return self.sessions.update_one(
            {"user_id": user_id},
            {"$set": {key: value}},
            upsert=True
        )
    
    def get_session(self, user_id):
        """Get session data"""
        return self.sessions.find_one({"user_id": user_id}) or {}
    
    def clear_session(self, user_id):
        """Clear session data"""
        return self.sessions.delete_one({"user_id": user_id})
    
    def clear_session_key(self, user_id, key):
        """Clear specific session key"""
        return self.sessions.update_one(
            {"user_id": user_id},
            {"$unset": {key: ""}}
        )
    
    # Statistics
    def get_stats(self):
        """Get bot statistics"""
        return {
            "total_users": self.users.count_documents({}),
            "total_sudos": self.sudos.count_documents({}),
            "total_accounts": self.accounts.count_documents({"is_active": True}),
            "total_reports": self.reports.count_documents({}),
            "active_reports": self.reports.count_documents({"status": "running"})
        }
