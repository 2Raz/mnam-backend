"""
خدمة تتبع جلسات الموظفين
Employee Session Tracking Service
"""
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models.employee_session import (
    EmployeeSession, EmployeeAttendance, 
    OFFLINE_TIMEOUT_MINUTES
)
from ..models.user import User


class SessionTrackingService:
    """خدمة تتبع جلسات الموظفين"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ======== إدارة الجلسات ========
    
    def start_session(
        self,
        employee_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> EmployeeSession:
        """بدء جلسة جديدة عند تسجيل الدخول"""
        # إغلاق أي جلسات نشطة سابقة
        self._close_stale_sessions(employee_id)
        
        # إنشاء جلسة جديدة
        session = EmployeeSession(
            employee_id=employee_id,
            login_at=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent,
            is_active=True
        )
        self.db.add(session)
        
        # تحديث سجل الحضور اليومي
        self._update_attendance_on_login(employee_id)
        
        self.db.commit()
        self.db.refresh(session)
        return session
    
    def end_session(self, employee_id: str) -> None:
        """إنهاء الجلسة عند تسجيل الخروج"""
        active_session = self._get_active_session(employee_id)
        if active_session:
            active_session.close_session()
            self._update_attendance_on_logout(employee_id, active_session)
            self.db.commit()
    
    def heartbeat(self, employee_id: str) -> Dict:
        """تحديث نبضة الحياة"""
        active_session = self._get_active_session(employee_id)
        
        if not active_session:
            # لا يوجد جلسة نشطة - إنشاء واحدة
            active_session = self.start_session(employee_id)
        
        # تحديث آخر نبضة
        active_session.last_heartbeat = datetime.utcnow()
        
        # تحديث آخر نشاط في الحضور
        today = date.today()
        attendance = self._get_or_create_attendance(employee_id, today)
        attendance.last_activity = datetime.utcnow()
        
        self.db.commit()
        
        return {
            "session_id": active_session.id,
            "duration_minutes": active_session.calculated_duration_minutes,
            "is_online": True
        }
    
    # ======== الإحصائيات ========
    
    def get_my_session_stats(self, employee_id: str) -> Dict:
        """إحصائيات جلستي اليوم"""
        today = date.today()
        attendance = self._get_or_create_attendance(employee_id, today)
        active_session = self._get_active_session(employee_id)
        
        # حساب المدة الحالية
        current_duration = attendance.total_duration_minutes
        if active_session:
            current_duration += active_session.calculated_duration_minutes
        
        # هل متصل الآن؟
        is_online = False
        if active_session and active_session.last_heartbeat:
            minutes_since_heartbeat = (datetime.utcnow() - active_session.last_heartbeat).total_seconds() / 60
            is_online = minutes_since_heartbeat < OFFLINE_TIMEOUT_MINUTES
        
        return {
            "todayDuration": current_duration,
            "formattedDuration": self._format_duration(current_duration),
            "isOnline": is_online,
            "lastActivity": attendance.last_activity.isoformat() if attendance.last_activity else None,
            "firstLogin": attendance.first_login.isoformat() if attendance.first_login else None,
            "sessionsCount": attendance.total_sessions,
            "activitiesCount": attendance.activities_count
        }
    
    def get_employee_online_status(self, employee_id: str) -> Dict:
        """حالة اتصال موظف معين"""
        active_session = self._get_active_session(employee_id)
        today = date.today()
        attendance = self.db.query(EmployeeAttendance).filter(
            EmployeeAttendance.employee_id == employee_id,
            EmployeeAttendance.date == today
        ).first()
        
        is_online = False
        current_session_duration = 0
        
        if active_session and active_session.last_heartbeat:
            minutes_since_heartbeat = (datetime.utcnow() - active_session.last_heartbeat).total_seconds() / 60
            is_online = minutes_since_heartbeat < OFFLINE_TIMEOUT_MINUTES
            current_session_duration = active_session.calculated_duration_minutes
        
        total_duration = (attendance.total_duration_minutes if attendance else 0) + current_session_duration
        
        return {
            "isOnline": is_online,
            "todayDuration": total_duration,
            "formattedDuration": self._format_duration(total_duration),
            "lastActivity": attendance.last_activity.isoformat() if attendance and attendance.last_activity else None,
            "currentSessionStart": active_session.login_at.isoformat() if active_session else None
        }
    
    def get_all_employees_status(self) -> List[Dict]:
        """حالة جميع الموظفين (للمدير)"""
        employees = self.db.query(User).filter(
            User.is_active == True,
            User.is_system_owner == False
        ).all()
        
        result = []
        for emp in employees:
            status = self.get_employee_online_status(emp.id)
            result.append({
                "employeeId": emp.id,
                "employeeName": f"{emp.first_name} {emp.last_name}",
                **status
            })
        
        return result
    
    # ======== تقارير الحضور ========
    
    def get_attendance_report(
        self,
        period: str = "weekly",
        employee_id: Optional[str] = None
    ) -> Dict:
        """تقرير الحضور الأسبوعي/الشهري"""
        today = date.today()
        
        if period == "weekly":
            start_date = today - timedelta(days=today.weekday())
            end_date = today
            period_label = "الأسبوع الحالي"
        elif period == "monthly":
            start_date = today.replace(day=1)
            end_date = today
            period_label = "الشهر الحالي"
        else:
            start_date = today - timedelta(days=7)
            end_date = today
            period_label = "آخر 7 أيام"
        
        query = self.db.query(EmployeeAttendance).filter(
            EmployeeAttendance.date >= start_date,
            EmployeeAttendance.date <= end_date
        )
        
        if employee_id:
            query = query.filter(EmployeeAttendance.employee_id == employee_id)
        
        records = query.all()
        
        # تجميع البيانات حسب الموظف
        employee_data = {}
        for record in records:
            emp_id = record.employee_id
            if emp_id not in employee_data:
                employee_data[emp_id] = {
                    "employeeId": emp_id,
                    "employeeName": f"{record.employee.first_name} {record.employee.last_name}" if record.employee else "Unknown",
                    "totalDays": 0,
                    "totalMinutes": 0,
                    "totalActivities": 0,
                    "dailyDetails": []
                }
            
            employee_data[emp_id]["totalDays"] += 1
            employee_data[emp_id]["totalMinutes"] += record.total_duration_minutes
            employee_data[emp_id]["totalActivities"] += record.activities_count
            employee_data[emp_id]["dailyDetails"].append({
                "date": record.date.isoformat(),
                "duration": record.total_duration_minutes,
                "formattedDuration": self._format_duration(record.total_duration_minutes),
                "firstLogin": record.first_login.isoformat() if record.first_login else None,
                "activities": record.activities_count
            })
        
        # تنسيق النتائج
        employees_list = list(employee_data.values())
        for emp in employees_list:
            emp["formattedTotal"] = self._format_duration(emp["totalMinutes"])
            emp["averageDaily"] = emp["totalMinutes"] // emp["totalDays"] if emp["totalDays"] > 0 else 0
            emp["formattedAverage"] = self._format_duration(emp["averageDaily"])
        
        return {
            "period": period,
            "periodLabel": period_label,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "employees": employees_list,
            "summary": {
                "totalEmployees": len(employees_list),
                "totalHours": sum(e["totalMinutes"] for e in employees_list) // 60,
                "averageHoursPerEmployee": (sum(e["totalMinutes"] for e in employees_list) // 60) // max(len(employees_list), 1)
            }
        }
    
    # ======== دوال مساعدة ========
    
    def _get_active_session(self, employee_id: str) -> Optional[EmployeeSession]:
        """الحصول على الجلسة النشطة"""
        return self.db.query(EmployeeSession).filter(
            EmployeeSession.employee_id == employee_id,
            EmployeeSession.is_active == True
        ).first()
    
    def _close_stale_sessions(self, employee_id: str) -> None:
        """إغلاق الجلسات القديمة"""
        stale_sessions = self.db.query(EmployeeSession).filter(
            EmployeeSession.employee_id == employee_id,
            EmployeeSession.is_active == True
        ).all()
        
        for session in stale_sessions:
            session.close_session()
    
    def _get_or_create_attendance(self, employee_id: str, for_date: date) -> EmployeeAttendance:
        """الحصول على أو إنشاء سجل الحضور"""
        attendance = self.db.query(EmployeeAttendance).filter(
            EmployeeAttendance.employee_id == employee_id,
            EmployeeAttendance.date == for_date
        ).first()
        
        if not attendance:
            attendance = EmployeeAttendance(
                employee_id=employee_id,
                date=for_date
            )
            self.db.add(attendance)
            self.db.flush()
        
        return attendance
    
    def _update_attendance_on_login(self, employee_id: str) -> None:
        """تحديث الحضور عند تسجيل الدخول"""
        today = date.today()
        attendance = self._get_or_create_attendance(employee_id, today)
        
        if not attendance.first_login:
            attendance.first_login = datetime.utcnow()
        
        attendance.total_sessions += 1
        attendance.last_activity = datetime.utcnow()
    
    def _update_attendance_on_logout(self, employee_id: str, session: EmployeeSession) -> None:
        """تحديث الحضور عند تسجيل الخروج"""
        today = date.today()
        attendance = self._get_or_create_attendance(employee_id, today)
        
        attendance.last_logout = datetime.utcnow()
        attendance.total_duration_minutes += session.duration_minutes
        attendance.last_activity = datetime.utcnow()
    
    def _format_duration(self, minutes: int) -> str:
        """تنسيق المدة"""
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0:
            return f"{hours}س {mins}د"
        return f"{mins}د"
    
    def increment_activity_count(self, employee_id: str) -> None:
        """زيادة عداد الأنشطة (يستدعى من employee_performance_service)"""
        today = date.today()
        attendance = self._get_or_create_attendance(employee_id, today)
        attendance.activities_count += 1
        attendance.last_activity = datetime.utcnow()
        self.db.commit()
