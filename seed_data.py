from datetime import datetime, timedelta, timezone
import random

def get_moscow_now():
    return datetime.now(timezone(timedelta(hours=3)))

def seed(db, User, Medication, Event, BPLog):
    # Create doctor
    doc = User(name='Д-р Карпов', role='doctor', doctor_code='123456')
    db.session.add(doc)
    db.session.commit()

    patients = [
        {'name': 'Иванов Иван Иванович', 'age': 58,
         'drug': 'Эналаприл', 'dose': '10мг', 'window': ('08:00', '10:00'),
         'adherence_rate': 0.78, 'bp_base': (142, 89)},
        {'name': 'Петрова Мария Сергеевна', 'age': 62,
         'drug': 'Лозартан', 'dose': '50мг', 'window': ('08:00', '10:00'),
         'adherence_rate': 0.92, 'bp_base': (135, 82)},
        {'name': 'Сидоров Алексей Витальевич', 'age': 54,
         'drug': 'Амлодипин', 'dose': '5мг', 'window': ('20:00', '22:00'),
         'adherence_rate': 0.45, 'bp_base': (160, 98)},
    ]

    for p in patients:
        user = User(name=p['name'], role='patient',
                    doctor_code='123456',
                    bp_target_systolic=140, bp_target_diastolic=90)
        db.session.add(user)
        db.session.commit()

        med = Medication(user_id=user.id, drug_name=p['drug'],
                         dosage=p['dose'],
                         window_start=p['window'][0],
                         window_end=p['window'][1])
        db.session.add(med)
        db.session.commit()

        today = get_moscow_now()
        for i in range(30, 0, -1):
            day = today - timedelta(days=i)
            e_send = Event(user_id=user.id, medication_id=med.id,
                           event_type='reminder_sent',
                           timestamp=day.replace(hour=8, minute=0))
            db.session.add(e_send)

            if random.random() < p['adherence_rate']:
                delay = random.randint(60, 600)
                e_conf = Event(user_id=user.id, medication_id=med.id,
                               event_type='dose_confirmed',
                               timestamp=day.replace(hour=8, minute=0) + timedelta(seconds=delay),
                               metadata_json=f'{{"time_to_confirm_seconds": {delay}}}')
                db.session.add(e_conf)
            else:
                e_skip = Event(user_id=user.id, medication_id=med.id,
                               event_type='dose_skipped',
                               timestamp=day.replace(hour=9, minute=0))
                db.session.add(e_skip)

            if i % 2 == 0:
                noise_s = random.randint(-8, 8)
                noise_d = random.randint(-5, 5)
                bp = BPLog(user_id=user.id,
                           systolic=p['bp_base'][0] + noise_s,
                           diastolic=p['bp_base'][1] + noise_d,
                           context='normal',
                           timestamp=day.replace(hour=8, minute=30))
                db.session.add(bp)

        db.session.commit()
    return "Seeded."