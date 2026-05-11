import hmac
import json
import os

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from auth import require_admin
from db import get_db, now_iso

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_password() -> str:
    return os.environ.get('ADMIN_PASSWORD', '')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        provided = request.form.get('password') or ''
        expected = admin_password()
        if not expected:
            flash('ADMIN_PASSWORD ist nicht gesetzt. Bitte konfigurieren.', 'error')
            return render_template('admin_login.html'), 500
        if hmac.compare_digest(provided, expected):
            session['admin'] = True
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        flash('Falsches Passwort.', 'error')
        return render_template('admin_login.html'), 401
    return render_template('admin_login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    session.pop('admin', None)
    return redirect(url_for('buildings.index'))


@bp.route('/')
@require_admin
def dashboard():
    db = get_db()
    pending = db.execute(
        "SELECT COUNT(*) FROM building_suggestions WHERE status = 'pending'"
    ).fetchone()[0]
    buildings = db.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    reisekosten = db.execute("SELECT COUNT(*) FROM reisekosten").fetchone()[0]
    return render_template('admin/dashboard.html',
                           pending_suggestions=pending,
                           buildings_count=buildings,
                           reisekosten_count=reisekosten)


# ---------- buildings ----------

@bp.route('/buildings')
@require_admin
def buildings_list():
    db = get_db()
    rows = db.execute("SELECT * FROM buildings ORDER BY is_major DESC, name").fetchall()
    return render_template('admin/buildings.html', buildings=rows)


@bp.route('/buildings/new', methods=['GET', 'POST'])
@require_admin
def buildings_new():
    if request.method == 'POST':
        data = _building_from_form(request.form)
        if not data['kuerzel'] or not data['name']:
            flash('Kürzel und Name sind erforderlich.', 'error')
            return render_template('admin/building_form.html', building=data, mode='new'), 400
        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO buildings (kuerzel, name, adresse, campus, status, is_major,
                                       news_link, workplaces, size_sqm, notes)
                VALUES (:kuerzel, :name, :adresse, :campus, :status, :is_major,
                        :news_link, :workplaces, :size_sqm, :notes)
                """,
                data,
            )
            db.commit()
        except Exception as e:
            flash(f'Konnte Gebäude nicht anlegen: {e}', 'error')
            return render_template('admin/building_form.html', building=data, mode='new'), 400
        flash('Gebäude angelegt.', 'success')
        return redirect(url_for('admin.buildings_list'))
    return render_template('admin/building_form.html', building={}, mode='new')


@bp.route('/buildings/<int:bid>/edit', methods=['GET', 'POST'])
@require_admin
def buildings_edit(bid):
    db = get_db()
    row = db.execute("SELECT * FROM buildings WHERE id = ?", (bid,)).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        data = _building_from_form(request.form)
        if not data['kuerzel'] or not data['name']:
            flash('Kürzel und Name sind erforderlich.', 'error')
            return render_template('admin/building_form.html',
                                   building={**dict(row), **data, 'id': bid},
                                   mode='edit'), 400
        db.execute(
            """
            UPDATE buildings SET kuerzel = :kuerzel, name = :name, adresse = :adresse,
                campus = :campus, status = :status, is_major = :is_major,
                news_link = :news_link, workplaces = :workplaces,
                size_sqm = :size_sqm, notes = :notes
            WHERE id = :id
            """,
            {**data, 'id': bid},
        )
        db.commit()
        flash('Gebäude aktualisiert.', 'success')
        return redirect(url_for('admin.buildings_list'))
    return render_template('admin/building_form.html', building=dict(row), mode='edit')


@bp.route('/buildings/<int:bid>/delete', methods=['POST'])
@require_admin
def buildings_delete(bid):
    db = get_db()
    db.execute("DELETE FROM buildings WHERE id = ?", (bid,))
    db.commit()
    flash('Gebäude gelöscht.', 'success')
    return redirect(url_for('admin.buildings_list'))


def _building_from_form(form):
    return {
        'kuerzel': (form.get('kuerzel') or '').strip(),
        'name': (form.get('name') or '').strip(),
        'adresse': (form.get('adresse') or '').strip() or None,
        'campus': (form.get('campus') or '').strip() or None,
        'status': form.get('status') or 'healthy',
        'is_major': 1 if form.get('is_major') else 0,
        'news_link': (form.get('news_link') or '').strip() or None,
        'workplaces': _int_or_none(form.get('workplaces')),
        'size_sqm': _float_or_none(form.get('size_sqm')),
        'notes': (form.get('notes') or '').strip() or None,
    }


# ---------- suggestions ----------

@bp.route('/suggestions')
@require_admin
def suggestions_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, u.email AS user_email, b.kuerzel AS building_kuerzel, b.name AS building_name
        FROM building_suggestions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN buildings b ON b.id = s.building_id
        ORDER BY CASE WHEN s.status = 'pending' THEN 0 ELSE 1 END,
                 datetime(s.created_at) DESC
        """
    ).fetchall()
    suggestions = []
    for r in rows:
        d = dict(r)
        try:
            d['payload_parsed'] = json.loads(d['payload'] or '{}')
        except json.JSONDecodeError:
            d['payload_parsed'] = {}
        suggestions.append(d)
    return render_template('admin/suggestions.html', suggestions=suggestions)


@bp.route('/suggestions/<int:sid>/accept', methods=['POST'])
@require_admin
def suggestions_accept(sid):
    db = get_db()
    s = db.execute("SELECT * FROM building_suggestions WHERE id = ?", (sid,)).fetchone()
    if not s:
        abort(404)
    if s['status'] != 'pending':
        flash('Vorschlag bereits bearbeitet.', 'error')
        return redirect(url_for('admin.suggestions_list'))

    try:
        payload = json.loads(s['payload'] or '{}')
    except json.JSONDecodeError:
        payload = {}

    if s['kind'] == 'new':
        db.execute(
            """
            INSERT OR IGNORE INTO buildings (kuerzel, name, adresse, campus, status, is_major,
                                             news_link, workplaces, size_sqm, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get('kuerzel'), payload.get('name'), payload.get('adresse'),
                payload.get('campus'), payload.get('status', 'healthy'),
                1 if payload.get('is_major') else 0,
                payload.get('news_link') or None,
                payload.get('workplaces'), payload.get('size_sqm'),
                payload.get('notes') or None,
            ),
        )
    elif s['kind'] == 'edit' and s['building_id']:
        allowed = ('status', 'news_link', 'workplaces', 'size_sqm', 'notes',
                   'adresse', 'campus', 'is_major', 'name', 'kuerzel')
        sets = []
        vals = []
        for k in allowed:
            if k in payload:
                v = payload[k]
                if k == 'is_major':
                    v = 1 if v else 0
                sets.append(f"{k} = ?")
                vals.append(v)
        if sets:
            vals.append(s['building_id'])
            db.execute(f"UPDATE buildings SET {', '.join(sets)} WHERE id = ?", vals)

    db.execute(
        "UPDATE building_suggestions SET status = 'accepted', reviewed_at = ? WHERE id = ?",
        (now_iso(), sid),
    )
    db.commit()
    flash('Vorschlag übernommen.', 'success')
    return redirect(url_for('admin.suggestions_list'))


@bp.route('/suggestions/<int:sid>/reject', methods=['POST'])
@require_admin
def suggestions_reject(sid):
    db = get_db()
    db.execute(
        "UPDATE building_suggestions SET status = 'rejected', reviewed_at = ? WHERE id = ?",
        (now_iso(), sid),
    )
    db.commit()
    flash('Vorschlag abgelehnt.', 'success')
    return redirect(url_for('admin.suggestions_list'))


# ---------- reisekosten ----------

@bp.route('/reisekosten')
@require_admin
def reisekosten_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT r.*, u.email AS user_email
        FROM reisekosten r
        LEFT JOIN users u ON u.id = r.user_id
        ORDER BY datetime(r.created_at) DESC
        """
    ).fetchall()
    return render_template('admin/reisekosten.html', items=[dict(r) for r in rows])


@bp.route('/reisekosten/<int:rid>/edit', methods=['GET', 'POST'])
@require_admin
def reisekosten_edit(rid):
    db = get_db()
    row = db.execute(
        """
        SELECT r.*, u.email AS user_email
        FROM reisekosten r LEFT JOIN users u ON u.id = r.user_id
        WHERE r.id = ?
        """, (rid,)
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        data = {
            'destination': (request.form.get('destination') or '').strip(),
            'purpose': (request.form.get('purpose') or '').strip() or None,
            'antrag_date': (request.form.get('antrag_date') or '').strip(),
            'travel_start_date': (request.form.get('travel_start_date') or '').strip() or None,
            'travel_end_date': (request.form.get('travel_end_date') or '').strip() or None,
            'estimated_amount': _float_or_none(request.form.get('estimated_amount')),
            'advance_amount': _float_or_none(request.form.get('advance_amount')),
            'abrechnung_date': (request.form.get('abrechnung_date') or '').strip() or None,
            'final_amount': _float_or_none(request.form.get('final_amount')),
            'settlement_date': (request.form.get('settlement_date') or '').strip() or None,
            'status': request.form.get('status') or row['status'],
            'updated_at': now_iso(),
            'id': rid,
        }
        if not data['destination'] or not data['antrag_date']:
            flash('Reiseziel und Antragsdatum sind erforderlich.', 'error')
            merged = {**dict(row), **data}
            return render_template('admin/reisekosten_form.html', item=merged), 400
        db.execute(
            """
            UPDATE reisekosten SET destination = :destination, purpose = :purpose,
                antrag_date = :antrag_date, travel_start_date = :travel_start_date,
                travel_end_date = :travel_end_date, estimated_amount = :estimated_amount,
                advance_amount = :advance_amount, abrechnung_date = :abrechnung_date,
                final_amount = :final_amount, settlement_date = :settlement_date,
                status = :status, updated_at = :updated_at
            WHERE id = :id
            """,
            data,
        )
        db.commit()
        flash('Reisekosten aktualisiert.', 'success')
        return redirect(url_for('admin.reisekosten_list'))
    return render_template('admin/reisekosten_form.html', item=dict(row))


@bp.route('/reisekosten/<int:rid>/delete', methods=['POST'])
@require_admin
def reisekosten_delete(rid):
    db = get_db()
    db.execute("DELETE FROM reisekosten WHERE id = ?", (rid,))
    db.commit()
    flash('Reisekostenantrag gelöscht.', 'success')
    return redirect(url_for('admin.reisekosten_list'))


def _int_or_none(v):
    if v is None or str(v).strip() == '':
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v):
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
