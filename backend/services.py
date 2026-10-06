import math, os, logging, asyncio
import numpy as np
from models import RiskLevel, Notification
from sqlalchemy.ext.asyncio import AsyncSession

threshold=float(os.getenv('ATTENDANCE_THRESHOLD','75'))
def project_attendance(history, weeks_ahead=4):
    if len(history)<2: return [history[-1] if history else 0]*weeks_ahead, 0.0
    slope, intercept=np.polyfit(np.arange(len(history)),history,1)
    values=(slope*np.arange(len(history),len(history)+weeks_ahead)+intercept).tolist()
    return [round(v,2) for v in values], float(slope)
def classify(current, projections):
    if current >= threshold and any(p < threshold for p in projections): return RiskLevel.projected_risk
    if current >=80: return RiskLevel.safe
    if current >=threshold: return RiskLevel.at_risk
    return RiskLevel.critical
def classes_to_recover(attended, conducted):
    if not conducted or attended/conducted >= threshold/100: return 0
    return math.ceil(((threshold/100)*conducted-attended)/(1-threshold/100))
def max_can_miss(attended, conducted): return max(0,math.floor(attended/(threshold/100)-conducted))
class WhatsAppService:
    async def send_message(self, db: AsyncSession, student_id:int, subject_id:int, phone:str, message:str, notification_type='critical'):
        mode=os.getenv('WHATSAPP_MODE','mock').lower()
        if mode == 'twilio':
            sid=os.getenv('TWILIO_ACCOUNT_SID'); auth=os.getenv('TWILIO_AUTH_TOKEN'); sender=os.getenv('TWILIO_WHATSAPP_FROM')
            if not all([sid,auth,sender]):
                raise RuntimeError('Twilio is enabled but TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, or TWILIO_WHATSAPP_FROM is missing')
            try:
                from twilio.rest import Client
                result=await asyncio.to_thread(lambda: Client(sid,auth).messages.create(from_=sender, to=f'whatsapp:{phone}', body=message))
                db.add(Notification(student_id=student_id,subject_id=subject_id,type=notification_type,message=f'[Twilio {result.sid} → {phone}] {message}',channel='whatsapp'))
                return {'mode':'twilio','to':phone,'queued':True,'message_sid':result.sid}
            except Exception as exc:
                logging.exception('TWILIO SEND FAILED')
                db.add(Notification(student_id=student_id,subject_id=subject_id,type='delivery_failed',message=f'[Twilio delivery failed → {phone}] {exc}',channel='whatsapp'))
                return {'mode':'twilio','to':phone,'queued':False,'error':str(exc)}
        target=os.getenv('WHATSAPP_TEST_PHONE',phone)
        logging.info('WHATSAPP MOCK -> %s: %s', target, message)
        db.add(Notification(student_id=student_id,subject_id=subject_id,type=notification_type,message=f'[Mock → {target}] {message}',channel='whatsapp_mock'))
        return {'mode':'mock','to':target,'queued':True}
