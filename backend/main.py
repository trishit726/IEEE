import io, os, csv, base64
from datetime import date, timedelta, datetime
import pandas as pd, qrcode
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database import Base, engine, get_db, SessionLocal
from models import *
from services import project_attendance, classify, classes_to_recover, max_can_miss, WhatsAppService

SECRET=os.getenv('JWT_SECRET','development-secret'); pwd=CryptContext(schemes=['bcrypt'],deprecated='auto')
app=FastAPI(title='AttendSure API'); app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

async def current_user(authorization: str|None=Header(None), db:AsyncSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Authentication required')
    try: payload=jwt.decode(authorization[7:],SECRET,algorithms=['HS256']); uid=int(payload['sub'])
    except (JWTError,KeyError,ValueError): raise HTTPException(401,'Invalid or expired token')
    user=await db.get(User,uid)
    if not user: raise HTTPException(401,'User not found')
    return user
def role_required(*roles):
    async def check(user=Depends(current_user)):
        if user.role.value not in roles: raise HTTPException(403,'Insufficient role')
        return user
    return check

async def student_for(student_id, db):
    s=await db.get(Student,student_id)
    if not s: raise HTTPException(404,'Student not found')
    return s
async def attendance_payload(student_id, db):
    s=await student_for(student_id,db); subjects=(await db.execute(select(Subject).where(Subject.department_id==s.department_id))).scalars().all(); out=[]
    for subj in subjects:
        conducted=(await db.scalar(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.student_id==s.id,AttendanceRecord.subject_id==subj.id))) or 0
        attended=(await db.scalar(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.student_id==s.id,AttendanceRecord.subject_id==subj.id,AttendanceRecord.status==AttendanceStatus.present))) or 0
        out.append({'subject_id':subj.id,'subject':subj.name,'code':subj.code,'classes_attended':attended,'classes_conducted':conducted,'current_percentage':round(attended/conducted*100,2) if conducted else 0,'remaining_planned_classes':max(0,subj.total_classes_planned-conducted)})
    return out
async def recalculate(student_id, db, notify=False):
    rows=await attendance_payload(student_id,db)
    for row in rows:
        histories=(await db.execute(select(WeeklySummary.percentage).where(WeeklySummary.student_id==student_id,WeeklySummary.subject_id==row['subject_id']).order_by(WeeklySummary.week_number))).scalars().all()
        projected,slope=project_attendance(list(histories)); risk=classify(row['current_percentage'],projected)
        old=await db.scalar(select(Prediction).where(Prediction.student_id==student_id,Prediction.subject_id==row['subject_id']))
        vals=dict(current_percentage=row['current_percentage'],projected_week_1=projected[0],projected_week_2=projected[1],projected_week_3=projected[2],projected_week_4=projected[3],trend_slope=slope,risk_level=risk,classes_to_recover=classes_to_recover(row['classes_attended'],row['classes_conducted']))
        if old:
            for k,v in vals.items(): setattr(old,k,v)
        else: db.add(Prediction(student_id=student_id,subject_id=row['subject_id'],**vals))
    await db.commit()
    # Upload-triggered warnings are logged through the replaceable mock adapter.
    # A production adapter can replace this class without changing import logic.
    deliveries=[]
    if notify:
        student=await db.get(Student,student_id); user=await db.get(User,student.user_id)
        for row in rows:
            prediction=await db.scalar(select(Prediction).where(Prediction.student_id==student_id,Prediction.subject_id==row['subject_id']))
            if prediction and prediction.risk_level in (RiskLevel.critical,RiskLevel.projected_risk):
                subject=await db.get(Subject,row['subject_id'])
                if prediction.risk_level==RiskLevel.critical:
                    message=f'🔔 AttendSure Attendance Alert\n\nHello {user.name} 👋\n\nYour {subject.name} attendance is currently {row["current_percentage"]}%.\n\nRequired attendance: 75%\nRisk Level: Critical 🔴\n\n📚 Classes needed to recover: {prediction.classes_to_recover}\n\n— AttendSure'
                else:
                    week=next((i+1 for i,v in enumerate([prediction.projected_week_1,prediction.projected_week_2,prediction.projected_week_3,prediction.projected_week_4]) if v < 75),4)
                    message=f'⚠️ AttendSure Early Warning\n\nHello {user.name} 👋\n\nYour {subject.name} attendance is currently {row["current_percentage"]}%.\n\nBased on your recent attendance trend, your attendance may fall below 75% in approximately {week} weeks.\n\nRecommended action: Attend the next {max(1,prediction.classes_to_recover)} {subject.name} classes.\n\n— AttendSure'
                service=WhatsAppService()
                deliveries.append(await service.send_message(db,student_id,subject.id,user.phone,message,prediction.risk_level.value))
                deliveries.append(await service.send_message(db,student_id,subject.id,user.parent_phone,f'Dear Parent of {user.name},\n\n{message}',prediction.risk_level.value))
        await db.commit()
    return deliveries

@app.on_event('startup')
async def startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        if not await db.scalar(select(User.id).limit(1)): await seed(db)

async def seed(db):
    cse=Department(name='Computer Science & Engineering',code='CSE'); ece=Department(name='Electronics & Communication',code='ECE'); aiml=Department(name='AI & Machine Learning',code='AIML'); db.add_all([cse,ece,aiml]); await db.flush()
    cse_subjects=[('Data Structures & Algorithms','DSA'),('Database Management Systems','DBMS'),('Python Programming','PYTHON'),('Engineering Mathematics','MATHS'),('Computer Networks','CN')]
    subs=[]
    for n,c in cse_subjects: subs.append(Subject(name=n,code=c,department_id=cse.id,semester=3,total_classes_planned=65))
    for d in [ece,aiml]: subs.extend([Subject(name=f'{d.code} Foundations',code=f'{d.code}101',department_id=d.id,semester=3,total_classes_planned=60)])
    db.add_all(subs); await db.flush()
    mentor=User(name='Dr. Priya Nair',email='mentor@demo.com',password_hash=pwd.hash('demo123'),role=Role.mentor,phone='+919876543210',parent_phone='+919876543211'); hod=User(name='Prof. Arun Rao',email='hod@demo.com',password_hash=pwd.hash('demo123'),role=Role.hod,phone='+919876543210',parent_phone='+919876543211'); exam=User(name='Exam Cell',email='examcell@demo.com',password_hash=pwd.hash('demo123'),role=Role.exam_cell,phone='+919876543210',parent_phone='+919876543211'); db.add_all([mentor,hod,exam]); await db.flush()
    names=['Rahul Sharma','Ananya Iyer','Vikram Singh','Meera Joshi','Arjun Patel','Kavya Reddy','Rohan Das','Sneha Kulkarni','Aditya Menon','Isha Gupta','Nikhil Shah','Pooja Verma','Karan Malhotra','Aditi Rao','Siddharth Jain']
    students=[]
    for i,name in enumerate(names):
        u=User(name=name,email='student@demo.com' if i==0 else f'cse{i+1}@demo.com',password_hash=pwd.hash('demo123'),role=Role.student,phone='+919876543210',parent_phone='+919876543211'); db.add(u); await db.flush(); students.append(Student(user_id=u.id,student_id_number=f'CS2025{i+1:03d}',department_id=cse.id,semester=3,mentor_id=mentor.id,year_of_joining=2025))
    for d,prefix in [(ece,'EC'),(aiml,'AI')]:
        for i in range(5):
            u=User(name=f'{d.code} Student {i+1}',email=f'{prefix.lower()}{i+1}@demo.com',password_hash=pwd.hash('demo123'),role=Role.student,phone='+919876543210',parent_phone='+919876543211'); db.add(u); await db.flush(); students.append(Student(user_id=u.id,student_id_number=f'{prefix}2025{i+1:03d}',department_id=d.id,semester=3,mentor_id=mentor.id,year_of_joining=2025))
    db.add_all(students); await db.flush()
    rahul=students[0]; totals=[(34,50),(37,50),(41,50),(39,50),(43,50)]; histories=[[74,72,70,69,68,68],[82,80,77,75,74,74],[78,79,80,81,82,82],[85,83,81,80,79,78],[82,84,85,86,86,86]]
    today=date.today()
    for si,s in enumerate(students):
        department_subs=[x for x in subs if x.department_id==s.department_id]
        for j,sub in enumerate(department_subs):
            attended,conducted=(totals[j] if s.id==rahul.id and j<5 else (38+(si+j)%10,50))
            for k in range(conducted): db.add(AttendanceRecord(student_id=s.id,subject_id=sub.id,date=today-timedelta(days=conducted-k),status=AttendanceStatus.present if k<attended else AttendanceStatus.absent))
            hist=histories[j] if s.id==rahul.id and j<5 else [76+(si+j+t)%10 for t in range(6)]
            for w,pct in enumerate(hist): db.add(WeeklySummary(student_id=s.id,subject_id=sub.id,week_number=w+1,week_start_date=today-timedelta(days=(6-w)*7),classes_conducted=8,classes_attended=round(pct*.08),percentage=pct))
    await db.commit()
    for s in students: await recalculate(s.id,db)

@app.post('/api/auth/login')
async def login(body:dict,db:AsyncSession=Depends(get_db)):
    u=await db.scalar(select(User).where(User.email==body.get('email','')))
    if not u or not pwd.verify(body.get('password',''),u.password_hash): raise HTTPException(401,'Invalid email or password')
    token=jwt.encode({'sub':str(u.id),'role':u.role.value,'exp':datetime.utcnow()+timedelta(hours=24)},SECRET,algorithm='HS256')
    return {'access_token':token,'role':u.role.value,'user_id':u.id,'name':u.name}
@app.get('/api/auth/me')
async def me(user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    st=await db.scalar(select(Student).where(Student.user_id==user.id)); return {'id':user.id,'name':user.name,'role':user.role.value,'student_id':st.id if st else None}
@app.get('/api/students/{student_id}/attendance')
async def attendance(student_id:int, user=Depends(current_user),db:AsyncSession=Depends(get_db)): return await attendance_payload(student_id,db)
@app.get('/api/students/{student_id}/projection')
async def projection(student_id:int,user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await recalculate(student_id,db); ps=(await db.execute(select(Prediction,Subject).join(Subject,Prediction.subject_id==Subject.id).where(Prediction.student_id==student_id))).all(); return [{'subject_id':p.subject_id,'subject':s.name,'current_percentage':p.current_percentage,'projections':[p.projected_week_1,p.projected_week_2,p.projected_week_3,p.projected_week_4],'trend_slope':p.trend_slope,'risk_level':p.risk_level.value} for p,s in ps]
@app.get('/api/students/{student_id}/recovery-plan')
async def recovery(student_id:int,user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    return [{**r,'classes_to_recover':classes_to_recover(r['classes_attended'],r['classes_conducted']),'max_can_miss':max_can_miss(r['classes_attended'],r['classes_conducted'])} for r in await attendance_payload(student_id,db)]
@app.get('/api/students/{student_id}/profile')
async def profile(student_id:int,user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    s=await student_for(student_id,db); u=await db.get(User,s.user_id); d=await db.get(Department,s.department_id); m=await db.get(User,s.mentor_id); return {'name':u.name,'student_id_number':s.student_id_number,'department':d.name,'semester':s.semester,'mentor':m.name if m else None,'phone':u.phone,'parent_phone':u.parent_phone}
@app.get('/api/notifications/{student_id}')
async def notifications(student_id:int,user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    ns=(await db.execute(select(Notification).where(Notification.student_id==student_id).order_by(Notification.sent_at.desc()))).scalars().all(); return [{'id':n.id,'type':n.type,'message':n.message,'sent_at':n.sent_at.isoformat(),'channel':n.channel} for n in ns]
@app.post('/api/notifications/send-whatsapp/{student_id}/{subject_id}')
async def send_whatsapp(student_id:int,subject_id:int,user=Depends(current_user),db:AsyncSession=Depends(get_db)):
    s=await student_for(student_id,db); u=await db.get(User,s.user_id); sub=await db.get(Subject,subject_id); rows=await attendance_payload(student_id,db); row=next((x for x in rows if x['subject_id']==subject_id),None)
    if not row: raise HTTPException(404,'Attendance missing')
    recovery=classes_to_recover(row['classes_attended'],row['classes_conducted']); msg=f'🔔 AttendSure Attendance Alert\n\nHello {u.name} 👋\n\nYour {sub.name} attendance is currently {row["current_percentage"]}%.\n\nRequired attendance: 75%\nRisk Level: Critical 🔴\n\n📚 Classes needed to recover: {recovery}\n\n— AttendSure'
    service=WhatsAppService(); await service.send_message(db,s.id,sub.id,u.phone,msg); await service.send_message(db,s.id,sub.id,u.parent_phone,f'Dear Parent of {u.name},\n\n{msg}'); await db.commit(); return {'sent':True,'recipient':os.getenv('WHATSAPP_TEST_PHONE','+917391936044'),'mode':'mock'}
@app.get('/api/attendance/sample-csv')
async def sample_csv():
    text='student_id,subject_code,date,status\nCS2025001,DSA,2026-10-01,Present\nCS2025001,DBMS,2026-10-01,Absent\n'; return StreamingResponse(iter([text]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=attendance_sample.csv'})
@app.post('/api/attendance/upload')
async def upload(file:UploadFile=File(...),user=Depends(role_required('mentor','hod','exam_cell')),db:AsyncSession=Depends(get_db)):
    try:
        raw=await file.read(); df=pd.read_excel(io.BytesIO(raw)) if file.filename.lower().endswith(('.xlsx','.xls')) else pd.read_csv(io.BytesIO(raw))
    except Exception as e: raise HTTPException(400,f'Unable to read file: {e}')
    needed={'student_id','subject_code','date','status'}
    if not needed.issubset(df.columns): raise HTTPException(400,f'Missing columns: {", ".join(sorted(needed-set(df.columns)))}')
    errors=[]; changed=set()
    for i,r in df.iterrows():
        try:
            student=await db.scalar(select(Student).where(Student.student_id_number==str(r.student_id))); subject=await db.scalar(select(Subject).where(Subject.code==str(r.subject_code))); dt=pd.to_datetime(r.date).date(); status=str(r.status).lower()
            if not student: raise ValueError('student_id not found')
            if not subject: raise ValueError('subject_code not found')
            if status not in ('present','absent'): raise ValueError('status must be Present or Absent')
            db.add(AttendanceRecord(student_id=student.id,subject_id=subject.id,date=dt,status=AttendanceStatus(status))); changed.add(student.id)
        except Exception as e: errors.append({'row':int(i)+2,'reason':str(e)})
    await db.commit()
    deliveries=[]
    for sid in changed: deliveries.extend(await recalculate(sid,db,True))
    return {'total_rows':len(df),'valid_rows':len(df)-len(errors),'invalid_rows':len(errors),'errors':errors,'notification_attempts':len(deliveries),'notification_sent':sum(1 for item in deliveries if item.get('queued')),'notification_failures':[item for item in deliveries if not item.get('queued')]}
def qr_bytes():
    b=io.BytesIO(); qrcode.make(os.getenv('FRONTEND_URL','http://localhost:5173')+'/student').save(b,format='PNG'); b.seek(0); return b
@app.get('/api/qr/portal')
async def qr_portal(): return {'image_base64':base64.b64encode(qr_bytes().read()).decode(),'url':os.getenv('FRONTEND_URL','http://localhost:5173')+'/student'}
@app.get('/api/qr/download')
async def qr_download(): return StreamingResponse(qr_bytes(),media_type='image/png',headers={'Content-Disposition':'attachment; filename=attendsure-portal.png'})
