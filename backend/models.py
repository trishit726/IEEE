from datetime import datetime, date
from sqlalchemy import String, Integer, Float, Date, DateTime, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
import enum

class Role(str, enum.Enum): student='student'; mentor='mentor'; hod='hod'; exam_cell='exam_cell'
class AttendanceStatus(str, enum.Enum): present='present'; absent='absent'
class RiskLevel(str, enum.Enum): safe='safe'; at_risk='at_risk'; critical='critical'; projected_risk='projected_risk'

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120)); email: Mapped[str]=mapped_column(String(150),unique=True); password_hash: Mapped[str]=mapped_column(String(255)); role: Mapped[Role]=mapped_column(Enum(Role)); phone: Mapped[str]=mapped_column(String(30)); parent_phone: Mapped[str]=mapped_column(String(30)); created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Department(Base):
    __tablename__='departments'; id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120)); code: Mapped[str]=mapped_column(String(20),unique=True)
class Subject(Base):
    __tablename__='subjects'; id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120)); code: Mapped[str]=mapped_column(String(30),unique=True); department_id: Mapped[int]=mapped_column(ForeignKey('departments.id')); semester: Mapped[int]=mapped_column(Integer); total_classes_planned: Mapped[int]=mapped_column(Integer,default=60)
class Student(Base):
    __tablename__='students'; id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),unique=True); student_id_number: Mapped[str]=mapped_column(String(40),unique=True); department_id: Mapped[int]=mapped_column(ForeignKey('departments.id')); semester: Mapped[int]=mapped_column(Integer); mentor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True); year_of_joining: Mapped[int]=mapped_column(Integer)
class AttendanceRecord(Base):
    __tablename__='attendance_records'; id: Mapped[int]=mapped_column(primary_key=True); student_id: Mapped[int]=mapped_column(ForeignKey('students.id')); subject_id: Mapped[int]=mapped_column(ForeignKey('subjects.id')); date: Mapped[date]=mapped_column(Date); status: Mapped[AttendanceStatus]=mapped_column(Enum(AttendanceStatus))
class WeeklySummary(Base):
    __tablename__='attendance_weekly_summary'; id: Mapped[int]=mapped_column(primary_key=True); student_id: Mapped[int]=mapped_column(ForeignKey('students.id')); subject_id: Mapped[int]=mapped_column(ForeignKey('subjects.id')); week_number: Mapped[int]=mapped_column(Integer); week_start_date: Mapped[date]=mapped_column(Date); classes_conducted: Mapped[int]=mapped_column(Integer); classes_attended: Mapped[int]=mapped_column(Integer); percentage: Mapped[float]=mapped_column(Float); __table_args__=(UniqueConstraint('student_id','subject_id','week_number'),)
class Prediction(Base):
    __tablename__='attendance_predictions'; id: Mapped[int]=mapped_column(primary_key=True); student_id: Mapped[int]=mapped_column(ForeignKey('students.id')); subject_id: Mapped[int]=mapped_column(ForeignKey('subjects.id')); current_percentage: Mapped[float]=mapped_column(Float); projected_week_1: Mapped[float]=mapped_column(Float); projected_week_2: Mapped[float]=mapped_column(Float); projected_week_3: Mapped[float]=mapped_column(Float); projected_week_4: Mapped[float]=mapped_column(Float); trend_slope: Mapped[float]=mapped_column(Float); risk_level: Mapped[RiskLevel]=mapped_column(Enum(RiskLevel)); classes_to_recover: Mapped[int]=mapped_column(Integer); calculated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Notification(Base):
    __tablename__='notifications'; id: Mapped[int]=mapped_column(primary_key=True); student_id: Mapped[int]=mapped_column(ForeignKey('students.id')); subject_id: Mapped[int|None]=mapped_column(ForeignKey('subjects.id'),nullable=True); type: Mapped[str]=mapped_column(String(30)); message: Mapped[str]=mapped_column(Text); sent_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); channel: Mapped[str]=mapped_column(String(30))
