from flask import (Flask, render_template, request,
                   jsonify, session, redirect, url_for, send_file)
from models import db, User, Medication, Event, BPLog, DemoRequest, get_moscow_now
from datetime import datetime, timedelta, timezone
import json, io, os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'neurokeep-demo-2026-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///neurokeep.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def log_event(user_id, event_type, medication_id=None, metadata=None):
    try:
        evt = Event(
            user_id=user_id,
            medication_id=medication_id,
            event_type=event_type,
            metadata_json=json.dumps(metadata or {})
        )
        db.session.add(evt)
        db.session.commit()
    except Exception as err:
        print(f"Event logging error: {err}")
        db.session.rollback()

def get_adherence_last_n_days(user_id, n=7):
    results = []
    today = get_moscow_now().date()
    meds = Medication.query.filter_by(user_id=user_id).all()
    total_meds = len(meds)
    if total_meds == 0:
        return []
    for i in range(n - 1, -1, -1):
        day = today - timedelta(days=i)
        confirmed = Event.query.filter(
            Event.user_id == user_id,
            Event.event_type == 'dose_confirmed',
            db.func.date(Event.timestamp) == day
        ).count()
        results.append({
            'date': day.strftime('%a' if n <= 7 else '%d/%m'),
            'full_date': str(day),
            'taken': min(confirmed, total_meds),
            'total': total_meds
        })
    return results

def get_bp_last_7_days(user_id):
    today = get_moscow_now().date()
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        log = BPLog.query.filter(
            BPLog.user_id == user_id,
            db.func.date(BPLog.timestamp) == day
        ).order_by(BPLog.timestamp.desc()).first()
        result.append({
            'date': day.strftime('%d/%m'),
            'systolic': log.systolic if log else None,
            'diastolic': log.diastolic if log else None
        })
    return result

def calc_streak(user_id):
    streak = 0
    today = get_moscow_now().date()
    for i in range(0, 90):
        day = today - timedelta(days=i)
        count = Event.query.filter(
            Event.user_id == user_id,
            Event.event_type == 'dose_confirmed',
            db.func.date(Event.timestamp) == day
        ).count()
        if count > 0:
            streak += 1
        else:
            break
    return streak

def is_within_window(window_start, window_end):
    now = get_moscow_now().strftime('%H:%M')
    return window_start <= now <= window_end

def get_risk_level(adherence_pct, last_bp_sys):
    if adherence_pct >= 80 and (last_bp_sys is None or last_bp_sys < 140):
        return 'low'
    elif adherence_pct >= 60:
        return 'medium'
    else:
        return 'high'

# ─────────────────────────────────────────
# SECTION A: LANDING PAGE
# ─────────────────────────────────────────

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/demo_request', methods=['POST'])
def demo_request():
    try:
        req = DemoRequest(
            name=request.form.get('name'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            role=request.form.get('role')
        )
        db.session.add(req)
        db.session.commit()
        return render_template('landing.html', demo_success=True)
    except Exception as err:
        return render_template('landing.html', error="Ошибка отправки")

# ─────────────────────────────────────────
# SECTION B: PATIENT ONBOARDING
# ─────────────────────────────────────────

TIME_WINDOWS = {
    'morning':   ('08:00', '10:00', 'Утро 8–10'),
    'afternoon': ('14:00', '16:00', 'День 14–16'),
    'evening':   ('20:00', '22:00', 'Вечер 20–22'),
}

@app.route('/onboarding/1', methods=['GET', 'POST'])
def onboarding_1():
    if request.method == 'POST':
        session['onb_meds'] = []
        names = request.form.getlist('drug_name')
        doses = request.form.getlist('dosage')
        windows = request.form.getlist('time_window')
        for n, d, w in zip(names, doses, windows):
            if n.strip():
                session['onb_meds'].append({
                    'drug_name': n.strip(),
                    'dosage': d.strip(),
                    'window': w
                })
        return redirect(url_for('onboarding_2'))
    return render_template('onboarding_1.html', time_windows=TIME_WINDOWS)

@app.route('/onboarding/2', methods=['GET', 'POST'])
def onboarding_2():
    if request.method == 'POST':
        try:
            session['bp_target_sys'] = int(request.form.get('systolic', 140))
            session['bp_target_dia'] = int(request.form.get('diastolic', 90))
            return redirect(url_for('onboarding_3'))
        except ValueError:
            return render_template('onboarding_2.html', error="Неверный формат чисел")
    return render_template('onboarding_2.html')

@app.route('/onboarding/3', methods=['GET', 'POST'])
def onboarding_3():
    error = None
    if request.method == 'POST':
        name = request.form.get('name', 'Пациент')
        phone = request.form.get('phone', '')
        doctor_code = request.form.get('doctor_code', '').strip()

        linked_doctor = None
        if doctor_code:
            linked_doctor = User.query.filter_by(
                role='doctor', doctor_code=doctor_code).first()
            if not linked_doctor:
                error = 'Код врача не найден. Попробуйте ещё раз или пропустите.'
                return render_template('onboarding_3.html', error=error)

        try:
            user = User(
                name=name,
                phone=phone,
                role='patient',
                bp_target_systolic=session.get('bp_target_sys', 140),
                bp_target_diastolic=session.get('bp_target_dia', 90),
                doctor_code=doctor_code or None
            )
            db.session.add(user)
            db.session.commit()

            for med_data in session.get('onb_meds', []):
                w = TIME_WINDOWS.get(med_data['window'], ('08:00', '10:00', ''))
                med = Medication(
                    user_id=user.id,
                    drug_name=med_data['drug_name'],
                    dosage=med_data['dosage'],
                    window_start=w[0],
                    window_end=w[1]
                )
                db.session.add(med)
            db.session.commit()

            session['user_id'] = user.id
            session['user_name'] = user.name
            log_event(user.id, 'onboarding_completed')
            return redirect(url_for('dashboard'))
        except Exception as err:
            error = "Ошибка создания профиля"
            db.session.rollback()

    return render_template('onboarding_3.html', error=error)

# ─────────────────────────────────────────
# SECTION C: PATIENT DASHBOARD
# ─────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('landing'))
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    meds = Medication.query.filter_by(user_id=user_id).all()
    today = get_moscow_now().date()

    confirmed_today = set()
    for e in Event.query.filter(
        Event.user_id == user_id,
        Event.event_type == 'dose_confirmed',
        db.func.date(Event.timestamp) == today
    ).all():
        if e.medication_id:
            confirmed_today.add(e.medication_id)

    for med in meds:
        med.in_window = is_within_window(med.window_start, med.window_end)
        med.confirmed_today = med.id in confirmed_today

    streak = calc_streak(user_id)
    adherence_data = get_adherence_last_n_days(user_id, 7)
    adherence_pct = round(
        sum(1 for d in adherence_data if d['taken'] >= d['total'] and d['total'] > 0)
        / max(len(adherence_data), 1) * 100
    )

    log_event(user_id, 'dashboard_opened')
    return render_template('dashboard.html',
        user=user, meds=meds, streak=streak,
        adherence_data=adherence_data, adherence_pct=adherence_pct
    )

@app.route('/confirm_dose/<int:med_id>', methods=['POST'])
def confirm_dose(med_id):
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 401
    user_id = session['user_id']
    try:
        log_event(user_id, 'dose_confirmed', medication_id=med_id,
                  metadata={'day_of_week': get_moscow_now().strftime('%A'),
                            'hour': get_moscow_now().hour})
        user = db.session.get(User, user_id)
        user.streak = calc_streak(user_id)
        db.session.commit()
        return jsonify({'success': True, 'streak': user.streak,
                        'message': 'Отлично! 🎉'})
    except Exception as err:
        return jsonify({'error': str(err)}), 500

@app.route('/skip_dose/<int:med_id>', methods=['POST'])
def skip_dose(med_id):
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 401
    log_event(session['user_id'], 'dose_skipped', medication_id=med_id)
    return jsonify({'success': True})

# ─────────────────────────────────────────
# SECTION D: BP LOGGING
# ─────────────────────────────────────────

BP_CONTEXTS = [
    ('normal',    'Обычный'),
    ('exercise',  'После тренировки'),
    ('stressed',  'Стресс'),
    ('coffee',    'После кофе'),
    ('salt',      'Много соли'),
    ('sleep',     'Плохой сон (<6ч)'),
]

@app.route('/bp', methods=['GET', 'POST'])
def bp_log():
    if 'user_id' not in session:
        return redirect(url_for('landing'))
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    error = None

    if request.method == 'POST':
        try:
            sys_val = int(request.form.get('systolic'))
            dia_val = int(request.form.get('diastolic'))
            ctx = request.form.get('context', 'normal')
            notes = request.form.get('notes', '')
            log = BPLog(user_id=user_id, systolic=sys_val,
                        diastolic=dia_val, context=ctx, notes=notes)
            db.session.add(log)
            db.session.commit()
            log_event(user_id, 'bp_logged',
                      metadata={'systolic': sys_val, 'diastolic': dia_val, 'context': ctx})
        except ValueError:
            error = "Неверный формат АД"

    bp_data = get_bp_last_7_days(user_id)
    valid = [d for d in bp_data if d['systolic']]
    avg_sys = round(sum(d['systolic'] for d in valid) / len(valid)) if valid else None
    avg_dia = round(sum(d['diastolic'] for d in valid) / len(valid)) if valid else None
    in_target = sum(1 for d in valid if d['systolic'] <= 135 and d['diastolic'] <= 85)
    in_target_pct = round(in_target / len(valid) * 100) if valid else 0

    improvement = None
    if len(valid) >= 4:
        mid = len(valid) // 2
        first_avg = sum(d['systolic'] for d in valid[:mid]) / mid
        second_avg = sum(d['systolic'] for d in valid[mid:]) / (len(valid) - mid)
        improvement = round((first_avg - second_avg) / first_avg * 100, 1)

    latest = BPLog.query.filter_by(user_id=user_id)\
        .order_by(BPLog.timestamp.desc()).limit(5).all()

    return render_template('bp_log.html',
        user=user, bp_data=bp_data, contexts=BP_CONTEXTS,
        avg_sys=avg_sys, avg_dia=avg_dia,
        in_target_pct=in_target_pct, improvement=improvement,
        latest_logs=latest, error=error,
        target_sys=user.bp_target_systolic,
        target_dia=user.bp_target_diastolic
    )

@app.route('/bp/export_pdf')
def export_pdf():
    if 'user_id' not in session:
        return redirect(url_for('landing'))
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    meds = Medication.query.filter_by(user_id=user_id).all()
    bp_data = get_bp_last_7_days(user_id)
    adherence = get_adherence_last_n_days(user_id, 30)
    adh_pct = round(sum(1 for d in adherence if d['taken'] >= d['total'] and d['total'] > 0)
                    / max(len(adherence), 1) * 100)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("NeuroKeep — Медицинский отчёт", styles['Title']))
    story.append(Paragraph(f"Пациент: {user.name}", styles['Normal']))
    story.append(Paragraph(f"Дата: {get_moscow_now().strftime('%d.%m.%Y')}", styles['Normal']))
    story.append(Spacer(1, 20))

    story.append(Paragraph("Лекарства", styles['Heading2']))
    for m in meds:
        story.append(Paragraph(f"• {m.drug_name} {m.dosage} ({m.window_start}–{m.window_end})", styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Приверженность (30 дней): {adh_pct}%", styles['Heading2']))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Артериальное давление (последние 7 дней)", styles['Heading2']))
    bp_table_data = [['Дата', 'Сист.', 'Диаст.']]
    for d in bp_data:
        bp_table_data.append([
            d['date'],
            str(d['systolic']) if d['systolic'] else '—',
            str(d['diastolic']) if d['diastolic'] else '—'
        ])
    t = Table(bp_table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563EB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph("Отчёт создан в NeuroKeep. Соответствует 152-ФЗ.", styles['Normal']))

    doc.build(story)
    buf.seek(0)
    log_event(user_id, 'pdf_exported')
    return send_file(buf, download_name=f'neurokeep_report_{user.name}.pdf',
                     mimetype='application/pdf')

# ─────────────────────────────────────────
# SECTION E: DOCTOR PORTAL
# ─────────────────────────────────────────

DOCTOR_USER = 'doctor'
DOCTOR_PASS = 'demo2026'

@app.route('/doctor/login', methods=['GET', 'POST'])
def doctor_login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == DOCTOR_USER and
                request.form.get('password') == DOCTOR_PASS):
            session['is_doctor'] = True
            log_event(None, 'doctor_portal_viewed')
            return redirect(url_for('doctor_dashboard'))
        error = 'Неверный логин или пароль'
    return render_template('doctor_login.html', error=error)

@app.route('/doctor/dashboard')
def doctor_dashboard():
    if not session.get('is_doctor'):
        return redirect(url_for('doctor_login'))
    patients = User.query.filter_by(role='patient').all()
    patient_data = []
    for p in patients:
        meds = Medication.query.filter_by(user_id=p.id).all()
        adh = get_adherence_last_n_days(p.id, 30)
        adh_pct = round(
            sum(1 for d in adh if d['taken'] >= d['total'] and d['total'] > 0)
            / max(len(adh), 1) * 100
        )
        last_bp = BPLog.query.filter_by(user_id=p.id)\
            .order_by(BPLog.timestamp.desc()).first()
        last_sys = last_bp.systolic if last_bp else None
        risk = get_risk_level(adh_pct, last_sys)
        patient_data.append({
            'user': p,
            'meds': meds,
            'adherence': adh_pct,
            'last_bp': f"{last_bp.systolic}/{last_bp.diastolic}" if last_bp else '—',
            'last_sys': last_sys,
            'risk': risk
        })
    return render_template('doctor_dashboard.html', patients=patient_data)

@app.route('/doctor/patient/<int:patient_id>')
def doctor_patient(patient_id):
    if not session.get('is_doctor'):
        return redirect(url_for('doctor_login'))
    patient = db.session.get(User, patient_id)
    meds = Medication.query.filter_by(user_id=patient_id).all()
    adh_30 = get_adherence_last_n_days(patient_id, 30)
    bp_30 = []
    today = get_moscow_now().date()
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        log = BPLog.query.filter(
            BPLog.user_id == patient_id,
            db.func.date(BPLog.timestamp) == day
        ).order_by(BPLog.timestamp.desc()).first()
        bp_30.append({
            'date': day.strftime('%d/%m'),
            'systolic': log.systolic if log else None,
            'diastolic': log.diastolic if log else None
        })
    events = Event.query.filter_by(user_id=patient_id)\
        .order_by(Event.timestamp.desc()).limit(10).all()
    return render_template('doctor_patient.html',
        patient=patient, meds=meds,
        adh_30=adh_30, bp_30=bp_30, events=events
    )

@app.route('/doctor/patient/<int:patient_id>/export_csv')
def export_csv(patient_id):
    if not session.get('is_doctor'):
        return redirect(url_for('doctor_login'))
    import csv
    patient = db.session.get(User, patient_id)
    events = Event.query.filter_by(user_id=patient_id)\
        .order_by(Event.timestamp.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['timestamp', 'event_type', 'medication_id', 'metadata'])
    for e in events:
        writer.writerow([e.timestamp, e.event_type, e.medication_id, e.metadata_json])
    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode()),
        download_name=f'neurokeep_{patient.name}_events.csv',
        mimetype='text/csv'
    )

# ─────────────────────────────────────────
# SECTION G: ADMIN EVENT VIEWER
# ─────────────────────────────────────────

@app.route('/admin/events')
def admin_events():
    events = Event.query.order_by(Event.timestamp.desc()).limit(50).all()
    return render_template('admin_events.html', events=events)

@app.route('/api/events/latest')
def api_events_latest():
    events = Event.query.order_by(Event.timestamp.desc()).limit(20).all()
    return jsonify([{
        'id': e.id,
        'timestamp': e.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'user_id': e.user_id,
        'event_type': e.event_type,
        'medication_id': e.medication_id,
        'metadata': e.metadata_json
    } for e in events])

# ─────────────────────────────────────────
# DEMO DATA SEED
# ─────────────────────────────────────────

@app.route('/seed_demo')
def seed_demo():
    if User.query.filter_by(role='doctor').first():
        return "Already seeded. <a href='/doctor/login'>Go to Doctor Portal</a>"
    from seed_data import seed
    seed(db, User, Medication, Event, BPLog)
    return "Demo data seeded! <a href='/doctor/login'>Go to Doctor Portal</a>"

# ─────────────────────────────────────────
# APP ENTRY
# ─────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8080, debug=False)