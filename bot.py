#!/usr/bin/env python3
"""
TELEGRAM AUTOMATION TEST LAB BOT
Complete bot with health check for Render.com
"""

import os
import sys
import asyncio
import logging
import time
import random
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from collections import Counter

# Flask for health check
try:
    from flask import Flask, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Telegram imports
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# Environment
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class Settings:
    """Application settings."""
    BOT_TOKEN: str = os.getenv(8800585127:AAEzkURyrTrE_JbBUndFFsfd5TA_gAGs7mg)
    OWNER_ID: int = int(os.getenv(7945654097))
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Dhaka")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TEST_MODE: bool = os.getenv("TEST_MODE", "true").lower() == "true"
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "5"))
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))

settings = Settings()

# ============================================================================
# LOGGING
# ============================================================================

def setup_logger(name: str = "telegram_bot") -> logging.Logger:
    """Setup logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

logger = setup_logger()

# ============================================================================
# MODELS
# ============================================================================

class UserRole(str, Enum):
    USER = "user"
    OWNER = "owner"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"

class JobStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    RUNNING = "running"
    ERROR = "error"

@dataclass
class User:
    """User model."""
    telegram_id: int
    username: Optional[str]
    first_name: str
    last_name: Optional[str] = None
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    joined_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    test_count: int = 0
    tests_passed: int = 0
    tests_failed: int = 0

@dataclass
class TestRun:
    """Test run model."""
    user_id: int
    test_name: str
    status: TestStatus = TestStatus.PENDING
    execution_time: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None
    details: Optional[str] = None

@dataclass
class ScheduledJob:
    """Scheduled job model."""
    name: str
    description: str
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    status: JobStatus = JobStatus.ENABLED
    error_message: Optional[str] = None

@dataclass
class Notification:
    """Notification model."""
    user_id: int
    message: str
    status: str = "pending"
    scheduled_for: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

# ============================================================================
# STORAGE
# ============================================================================

class InMemoryStorage:
    """In-memory storage for the bot."""
    
    def __init__(self):
        self.users: Dict[int, User] = {}
        self.test_runs: List[TestRun] = []
        self.scheduled_jobs: Dict[str, ScheduledJob] = {}
        self.notifications: List[Notification] = []
        self.logs: List[Dict[str, Any]] = []
        self._id_counter = 0
    
    def get_user(self, telegram_id: int) -> Optional[User]:
        return self.users.get(telegram_id)
    
    def create_user(self, telegram_id: int, username: str, first_name: str, last_name: str = None) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        self.users[telegram_id] = user
        logger.info(f"User created: {telegram_id} ({first_name})")
        return user
    
    def update_user_activity(self, telegram_id: int):
        user = self.get_user(telegram_id)
        if user:
            user.last_active = datetime.now()
    
    def get_all_users(self) -> List[User]:
        return list(self.users.values())
    
    def get_active_users_today(self) -> int:
        today = datetime.now().date()
        return sum(1 for u in self.users.values() 
                  if u.last_active.date() == today)
    
    def add_test_run(self, user_id: int, test_name: str, status: TestStatus, 
                     execution_time: float, details: str = None, error: str = None) -> TestRun:
        test_run = TestRun(
            user_id=user_id,
            test_name=test_name,
            status=status,
            execution_time=execution_time,
            details=details,
            error_message=error
        )
        self.test_runs.append(test_run)
        
        user = self.get_user(user_id)
        if user:
            user.test_count += 1
            if status == TestStatus.PASSED:
                user.tests_passed += 1
            elif status in [TestStatus.FAILED, TestStatus.ERROR]:
                user.tests_failed += 1
        
        return test_run
    
    def get_user_test_runs(self, user_id: int) -> List[TestRun]:
        return [t for t in self.test_runs if t.user_id == user_id]
    
    def get_test_stats(self) -> Dict[str, Any]:
        total = len(self.test_runs)
        passed = sum(1 for t in self.test_runs if t.status == TestStatus.PASSED)
        failed = sum(1 for t in self.test_runs if t.status == TestStatus.FAILED)
        error = sum(1 for t in self.test_runs if t.status == TestStatus.ERROR)
        success_rate = (passed / total * 100) if total > 0 else 0
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "error": error,
            "success_rate": round(success_rate, 1)
        }
    
    def get_most_used_tests(self, limit: int = 5) -> List[Dict[str, Any]]:
        test_names = [t.test_name for t in self.test_runs]
        counter = Counter(test_names)
        return [{"name": name, "count": count} 
                for name, count in counter.most_common(limit)]
    
    def add_job(self, name: str, description: str) -> ScheduledJob:
        job = ScheduledJob(name=name, description=description)
        self.scheduled_jobs[name] = job
        return job
    
    def get_job(self, name: str) -> Optional[ScheduledJob]:
        return self.scheduled_jobs.get(name)
    
    def get_all_jobs(self) -> List[ScheduledJob]:
        return list(self.scheduled_jobs.values())
    
    def add_notification(self, user_id: int, message: str, scheduled_for: datetime = None) -> int:
        notification = Notification(
            user_id=user_id,
            message=message,
            scheduled_for=scheduled_for
        )
        self.notifications.append(notification)
        return len(self.notifications) - 1
    
    def get_notification_stats(self) -> Dict[str, int]:
        total = len(self.notifications)
        delivered = sum(1 for n in self.notifications if n.status == "delivered")
        failed = sum(1 for n in self.notifications if n.status == "failed")
        pending = sum(1 for n in self.notifications if n.status == "pending")
        
        return {
            "total": total,
            "delivered": delivered,
            "failed": failed,
            "pending": pending
        }
    
    def add_log(self, level: str, event: str, user_id: int = None):
        log = {
            "id": self._id_counter,
            "level": level,
            "event": event,
            "user_id": user_id,
            "created_at": datetime.now().isoformat()
        }
        self._id_counter += 1
        self.logs.append(log)
        
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        
        logger.debug(f"Log: {level} - {event}")
    
    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.logs[-limit:]
    
    def get_recent_errors(self, limit: int = 5) -> List[Dict[str, Any]]:
        errors = [l for l in self.logs if l["level"] == "ERROR"]
        return errors[-limit:]
    
    def get_system_stats(self) -> Dict[str, Any]:
        test_stats = self.get_test_stats()
        return {
            "users": len(self.users),
            "active_today": self.get_active_users_today(),
            "tests_executed": test_stats["total"],
            "passed": test_stats["passed"],
            "failed": test_stats["failed"],
            "success_rate": test_stats["success_rate"],
            "total_jobs": len(self.scheduled_jobs),
            "enabled_jobs": sum(1 for j in self.scheduled_jobs.values() if j.enabled),
            "notifications": self.get_notification_stats()
        }
    
    def reset_test_data(self):
        self.test_runs = []
        self.notifications = []
        for user in self.users.values():
            user.test_count = 0
            user.tests_passed = 0
            user.tests_failed = 0
        self.add_log("INFO", "Test data reset")

# ============================================================================
# RATE LIMITER
# ============================================================================

class RateLimiter:
    """Simple rate limiter."""
    
    def __init__(self, max_requests: int = 5, period: int = 60):
        self.max_requests = max_requests
        self.period = period
        self.requests: Dict[int, List[datetime]] = {}
    
    async def check_limit(self, user_id: int) -> bool:
        now = datetime.now()
        
        if user_id not in self.requests:
            self.requests[user_id] = []
        
        cutoff = now - timedelta(seconds=self.period)
        self.requests[user_id] = [t for t in self.requests[user_id] if t > cutoff]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True
    
    def get_time_remaining(self, user_id: int) -> int:
        if user_id not in self.requests:
            return 0
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.period)
        recent = [t for t in self.requests[user_id] if t > cutoff]
        
        if len(recent) < self.max_requests:
            return 0
        
        oldest = min(recent)
        remaining = self.period - (now - oldest).total_seconds()
        return max(0, int(remaining))

# ============================================================================
# TEST ENGINE
# ============================================================================

class TestEngine:
    """Test automation engine."""
    
    @staticmethod
    async def run_test(user_id: int, test_name: str) -> Dict[str, Any]:
        start_time = time.time()
        
        try:
            test_method = getattr(TestEngine, f"_test_{test_name}", TestEngine._test_generic)
            result = await test_method(user_id)
            
            execution_time = time.time() - start_time
            success = result.get("success", False)
            status = TestStatus.PASSED if success else TestStatus.FAILED
            
            storage.add_test_run(
                user_id=user_id,
                test_name=test_name,
                status=status,
                execution_time=execution_time,
                details=result.get("details", ""),
                error=result.get("error")
            )
            
            storage.add_log(
                "INFO" if success else "ERROR",
                f"Test {test_name} {'passed' if success else 'failed'} for user {user_id}",
                user_id
            )
            
            return {
                "success": success,
                "test_name": test_name,
                "execution_time": round(execution_time, 2),
                "details": result.get("details", ""),
                "status": status.value,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            storage.add_test_run(
                user_id=user_id,
                test_name=test_name,
                status=TestStatus.ERROR,
                execution_time=execution_time,
                error=str(e)
            )
            
            storage.add_log("ERROR", f"Test {test_name} error for user {user_id}: {e}", user_id)
            
            return {
                "success": False,
                "test_name": test_name,
                "execution_time": round(execution_time, 2),
                "error": str(e),
                "status": "error",
                "timestamp": datetime.now().isoformat()
            }
    
    @staticmethod
    async def _test_generic(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.5)
        return {"success": True, "details": "Generic test passed"}
    
    @staticmethod
    async def _test_message(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.3)
        messages = ["Hello, World!", "Test message", "System is running", "Automation test"]
        return {"success": True, "details": f"Generated message: {random.choice(messages)}"}
    
    @staticmethod
    async def _test_db_read(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.4)
        user_count = len(storage.users)
        test_count = len(storage.test_runs)
        return {"success": True, "details": f"Read {user_count} users and {test_count} test runs"}
    
    @staticmethod
    async def _test_db_write(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.4)
        storage.add_log("INFO", f"Test write operation by user {user_id}", user_id)
        return {"success": True, "details": f"Wrote test log entry for user {user_id}"}
    
    @staticmethod
    async def _test_scheduler(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.5)
        jobs = storage.get_all_jobs()
        return {"success": True, "details": f"Scheduler test: {len(jobs)} jobs available"}
    
    @staticmethod
    async def _test_notification(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.3)
        storage.add_notification(user_id, "Test notification message")
        stats = storage.get_notification_stats()
        return {"success": True, "details": f"Notification test: {stats['total']} total"}
    
    @staticmethod
    async def _test_callback(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.2)
        return {"success": True, "details": "Callback test: processed successfully"}
    
    @staticmethod
    async def _test_api(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.6)
        success = random.choice([True, True, True, False])
        return {
            "success": success,
            "details": "API connectivity test completed" if success else "API test failed (simulated)"
        }
    
    @staticmethod
    async def _test_error(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.2)
        try:
            raise ValueError("This is a controlled test error")
        except Exception as e:
            return {
                "success": False,
                "details": f"Exception captured: {str(e)}",
                "error": str(e)
            }
    
    @staticmethod
    async def _test_queue(user_id: int) -> Dict[str, Any]:
        await asyncio.sleep(0.4)
        return {"success": True, "details": "Queue test: item queued and processed"}

# ============================================================================
# SCHEDULER
# ============================================================================

class SchedulerService:
    """Scheduler service."""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.setup_jobs()
    
    def setup_jobs(self):
        storage.add_job("system_health_check", "Run system health check every minute")
        storage.add_job("update_test_stats", "Update test statistics every 5 minutes")
        storage.add_job("generate_system_report", "Generate system report every hour")
        storage.add_job("clean_expired_records", "Clean expired test records daily")
        
        self.scheduler.add_job(
            self.system_health_check,
            IntervalTrigger(minutes=1),
            id="system_health_check"
        )
        self.scheduler.add_job(
            self.update_test_stats,
            IntervalTrigger(minutes=5),
            id="update_test_stats"
        )
        self.scheduler.add_job(
            self.generate_system_report,
            IntervalTrigger(hours=1),
            id="generate_system_report"
        )
        self.scheduler.add_job(
            self.clean_expired_records,
            CronTrigger(hour=0, minute=0),
            id="clean_expired_records"
        )
        
        logger.info("Scheduled jobs setup completed")
    
    async def system_health_check(self):
        logger.info("Running system health check...")
        try:
            user_count = len(storage.users)
            test_count = len(storage.test_runs)
            storage.add_log("INFO", f"Health check: {user_count} users, {test_count} tests")
            
            job = storage.get_job("system_health_check")
            if job:
                job.last_run = datetime.now()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            storage.add_log("ERROR", f"Health check failed: {e}")
            job = storage.get_job("system_health_check")
            if job:
                job.error_message = str(e)
                job.status = "error"
    
    async def update_test_stats(self):
        logger.info("Updating test statistics...")
        try:
            stats = storage.get_test_stats()
            storage.add_log("INFO", f"Stats updated: {stats['total']} total, {stats['passed']} passed")
            job = storage.get_job("update_test_stats")
            if job:
                job.last_run = datetime.now()
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")
            storage.add_log("ERROR", f"Failed to update stats: {e}")
    
    async def generate_system_report(self):
        logger.info("Generating system report...")
        try:
            stats = storage.get_system_stats()
            report = {
                "timestamp": datetime.now().isoformat(),
                "users": stats["users"],
                "tests": stats["tests_executed"],
                "success_rate": stats["success_rate"]
            }
            storage.add_log("INFO", f"Report generated: {report}")
            job = storage.get_job("generate_system_report")
            if job:
                job.last_run = datetime.now()
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            storage.add_log("ERROR", f"Failed to generate report: {e}")
    
    async def clean_expired_records(self):
        logger.info("Cleaning expired records...")
        try:
            cutoff = datetime.now() - timedelta(days=30)
            old_tests = [t for t in storage.test_runs if t.created_at < cutoff]
            for test in old_tests:
                storage.test_runs.remove(test)
            storage.add_log("INFO", f"Cleaned {len(old_tests)} expired records")
            job = storage.get_job("clean_expired_records")
            if job:
                job.last_run = datetime.now()
        except Exception as e:
            logger.error(f"Failed to clean records: {e}")
            storage.add_log("ERROR", f"Failed to clean records: {e}")
    
    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")
    
    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")

# ============================================================================
# KEYBOARDS
# ============================================================================

def get_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏠 Dashboard", callback_data="dashboard"),
        InlineKeyboardButton(text="👤 Profile", callback_data="profile")
    )
    builder.row(
        InlineKeyboardButton(text="🧪 Run Test", callback_data="run_test"),
        InlineKeyboardButton(text="📊 Statistics", callback_data="statistics")
    )
    builder.row(
        InlineKeyboardButton(text="⏰ Scheduler", callback_data="scheduler"),
        InlineKeyboardButton(text="ℹ️ About", callback_data="about")
    )
    return builder.as_markup()

def get_test_selector() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tests = [
        ("📝 Generate Message", "test_message"),
        ("💾 Database Read", "test_db_read"),
        ("💾 Database Write", "test_db_write"),
        ("⏰ Scheduler", "test_scheduler"),
        ("🔔 Notification", "test_notification"),
        ("🔄 Callback", "test_callback"),
        ("🌐 API Connectivity", "test_api"),
        ("⚠️ Error Handling", "test_error"),
        ("📋 Queue", "test_queue"),
    ]
    for name, callback in tests:
        builder.row(InlineKeyboardButton(text=name, callback_data=callback))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main"))
    return builder.as_markup()

# ============================================================================
# HANDLERS
# ============================================================================

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    user = storage.get_user(user_id)
    if user:
        storage.update_user_activity(user_id)
        welcome_msg = f"👋 Welcome back, {user.first_name}!"
    else:
        storage.create_user(user_id, username, first_name, last_name)
        welcome_msg = f"🤖 Welcome to the Automation Test Lab, {first_name}!"
        storage.add_log("INFO", f"New user: {user_id} ({first_name})")
    
    text = f"""{welcome_msg}

🧪 **Automation Test Lab**
*Testing & Development Environment*

🔹 Test automation engine
🔹 Real-time analytics
🔹 Scheduled jobs
🔹 Safe sandbox mode

Use the buttons below to explore the features.
"""
    
    await message.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🏠 **Main Menu**\nChoose an option below:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@router.callback_query(lambda c: c.data == "dashboard")
async def show_dashboard(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    user_id = callback.from_user.id
    user = storage.get_user(user_id)
    if not user:
        await callback.message.answer("Please start with /start first")
        return
    
    stats = storage.get_test_stats()
    user_tests = storage.get_user_test_runs(user_id)
    user_passed = sum(1 for t in user_tests if t.status == "passed")
    user_failed = sum(1 for t in user_tests if t.status in ["failed", "error"])
    user_success_rate = (user_passed / len(user_tests) * 100) if user_tests else 0
    
    text = f"""🏠 **Dashboard**

👤 **User:** {user.first_name}
📅 **Joined:** {user.joined_at.strftime('%Y-%m-%d %H:%M')}
🔄 **Last Active:** {user.last_active.strftime('%Y-%m-%d %H:%M')}

📊 **Your Statistics**
📝 Total Tests: {len(user_tests)}
✅ Passed: {user_passed}
❌ Failed: {user_failed}
📈 Success Rate: {round(user_success_rate, 1)}%

📊 **System Statistics**
👥 Total Users: {len(storage.users)}
🧪 Total Tests: {stats['total']}
✅ Passed: {stats['passed']}
📈 Success Rate: {stats['success_rate']}%
"""
    
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "profile")
async def show_profile(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    user_id = callback.from_user.id
    user = storage.get_user(user_id)
    if not user:
        await callback.message.answer("Please start with /start first")
        return
    
    user_tests = storage.get_user_test_runs(user_id)
    user_passed = sum(1 for t in user_tests if t.status == "passed")
    user_failed = sum(1 for t in user_tests if t.status in ["failed", "error"])
    success_rate = (user_passed / len(user_tests) * 100) if user_tests else 0
    
    text = f"""👤 **Profile**

**Basic Information**
🆔 ID: `{user.telegram_id}`
👤 Name: {user.first_name}{' ' + user.last_name if user.last_name else ''}
👥 Username: @{user.username or 'N/A'}
⭐ Role: {user.role.value}

**Activity**
📅 Joined: {user.joined_at.strftime('%Y-%m-%d %H:%M')}
🔄 Last Active: {user.last_active.strftime('%Y-%m-%d %H:%M')}

**Test Performance**
📝 Total Tests: {len(user_tests)}
✅ Passed: {user_passed}
❌ Failed: {user_failed}
📈 Success Rate: {round(success_rate, 1)}%
"""
    
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "statistics")
async def show_statistics(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    stats = storage.get_system_stats()
    most_used = storage.get_most_used_tests()
    errors = storage.get_recent_errors(3)
    
    text = f"""📊 **System Statistics**

👥 **Users**
Total: {stats['users']}
Active Today: {stats['active_today']}

🧪 **Tests**
Total: {stats['tests_executed']}
✅ Passed: {stats['passed']}
❌ Failed: {stats['failed']}
📈 Success Rate: {stats['success_rate']}%

⏰ **Scheduler**
Total Jobs: {stats['total_jobs']}
Enabled: {stats['enabled_jobs']}

🔔 **Notifications**
Total: {stats['notifications']['total']}
Delivered: {stats['notifications']['delivered']}
Failed: {stats['notifications']['failed']}

**Most Used Tests:**
"""
    
    for test in most_used:
        text += f"• {test['name']}: {test['count']} times\n"
    
    if errors:
        text += "\n**Recent Errors:**\n"
        for error in errors:
            text += f"• {error['event'][:50]}...\n"
    
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "run_test")
async def show_test_selector(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    text = """🧪 **Test Selector**

Choose a test to run:

✅ Safe sandbox environment
📊 Real-time results
⏱️ Execution timing
📝 Detailed output

Select a test from the buttons below:"""
    
    await callback.message.edit_text(text, reply_markup=get_test_selector(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith("test_"))
async def run_test(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    user_id = callback.from_user.id
    test_name = callback.data.replace("test_", "")
    
    if not await rate_limiter.check_limit(user_id):
        remaining = rate_limiter.get_time_remaining(user_id)
        await callback.answer(f"⏳ Rate limit active! Wait {remaining}s", show_alert=True)
        return
    
    await callback.answer("🧪 Running test...")
    
    result = await TestEngine.run_test(user_id, test_name)
    
    status_emoji = "✅" if result["success"] else "❌"
    status_text = "PASSED" if result["success"] else ("ERROR" if "error" in result else "FAILED")
    
    text = f"""🧪 **TEST RESULT**

**Test:** {result['test_name']}
**Status:** {status_emoji} {status_text}
**Execution Time:** {result['execution_time']}s
**Timestamp:** {result['timestamp'][:19]}

**Details:**
{result.get('details', 'No details available')}
"""
    
    if "error" in result:
        text += f"\n❌ **Error:** {result['error']}"
    
    user_tests = storage.get_user_test_runs(user_id)
    user_passed = sum(1 for t in user_tests if t.status == "passed")
    user_failed = sum(1 for t in user_tests if t.status in ["failed", "error"])
    
    text += f"\n\n📊 **Your Stats:** {user_passed} passed, {user_failed} failed"
    
    await callback.message.edit_text(text, reply_markup=get_test_selector(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "scheduler")
async def show_scheduler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    jobs = storage.get_all_jobs()
    
    text = "⏰ **Scheduler Status**\n\n"
    
    if not jobs:
        text += "No scheduled jobs."
    else:
        for job in jobs:
            status_emoji = "✅" if job.enabled else "❌"
            status_text = "Enabled" if job.enabled else "Disabled"
            last_run = job.last_run.strftime('%H:%M:%S') if job.last_run else "Never"
            
            text += f"**{job.name}**\n"
            text += f"  {status_emoji} {status_text}\n"
            text += f"  📝 {job.description}\n"
            text += f"  ⏱️ Last: {last_run}\n"
            if job.error_message:
                text += f"  ⚠️ Error: {job.error_message}\n"
            text += "\n"
    
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@router.callback_query(lambda c: c.data == "about")
async def show_about(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    
    text = """ℹ️ **About Automation Test Lab**

**Version:** 1.0.0
**Mode:** Sandbox

**Features:**
🧪 Test Automation Engine (9 tests)
📊 Real-time Analytics
⏰ Automated Scheduler (4 jobs)
🔔 Notification System
📝 Detailed Logging
🛡️ Rate Limiting

**Tech Stack:**
🐍 Python 3.12+
🤖 Aiogram 3.x
⏰ APScheduler
💾 In-Memory Storage

**Security:**
✅ Sandbox Environment
✅ Rate Limiting
✅ Input Validation
✅ Error Handling

🔒 **Test Mode:** {settings.TEST_MODE}

*For testing and development purposes only.*
"""
    
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")

# ============================================================================
# HEALTH CHECK (Flask)
# ============================================================================

def run_health_server():
    """Run Flask health check server for Render."""
    if not FLASK_AVAILABLE:
        logger.warning("Flask not available, health check disabled")
        return
    
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return "🤖 Telegram Test Bot is running!"
    
    @app.route('/health')
    def health():
        try:
            return jsonify({
                "status": "online",
                "users": len(storage.users),
                "tests": len(storage.test_runs),
                "uptime": "running"
            })
        except:
            return jsonify({"status": "starting"})
    
    try:
        app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Health server error: {e}")

# ============================================================================
# MAIN
# ============================================================================

# Global instances
storage = InMemoryStorage()
rate_limiter = RateLimiter(settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_PERIOD)
scheduler = SchedulerService()

async def main():
    """Main bot entry point."""
    # Start health server in background
    if FLASK_AVAILABLE:
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
        logger.info("Health check server started on port 8080")
    else:
        logger.warning("Health check server disabled (Flask not installed)")
    
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables")
        sys.exit(1)
    
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    dp = Dispatcher()
    dp.include_router(router)
    
    scheduler.start()
    
    logger.info("🤖 Automation Test Lab Bot started!")
    logger.info(f"🔒 Test Mode: {settings.TEST_MODE}")
    logger.info(f"👤 Owner ID: {settings.OWNER_ID}")
    logger.info(f"🐍 Python Version: {sys.version}")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
