from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta

db = SQLAlchemy()

def get_moscow_now():
    return datetime.now(timezone(timedelta(hours=3)))

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    role = db.Column(db.String(20), default='patient')
    streak = db.Column(db.Integer, default=0)
    bp_target_systolic = db.Column(db.Integer, default=140)
    bp_target_diastolic = db.Column(db.Integer, default=90)
    doctor_code = db.Column(db.String(6))
    created_at = db.Column(db.DateTime, default=get_moscow_now)

    medications = db.relationship('Medication', backref='user', lazy=True)
    events = db.relationship('Event', backref='user', lazy=True)
    bp_logs = db.relationship('BPLog', backref='user', lazy=True)

class Medication(db.Model):
    __tablename__ = 'medications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    drug_name = db.Column(db.String(100), nullable=False)
    dosage = db.Column(db.String(50))
    window_start = db.Column(db.String(5))
    window_end = db.Column(db.String(5))
    created_at = db.Column(db.DateTime, default=get_moscow_now)

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medications.id'), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=get_moscow_now)
    metadata_json = db.Column(db.String(500))

class BPLog(db.Model):
    __tablename__ = 'bp_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    systolic = db.Column(db.Integer, nullable=False)
    diastolic = db.Column(db.Integer, nullable=False)
    context = db.Column(db.String(50), default='normal')
    notes = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=get_moscow_now)

class DemoRequest(db.Model):
    __tablename__ = 'demo_requests'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    role = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=get_moscow_now)