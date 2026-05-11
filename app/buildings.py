import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import require_login, current_user
from db import get_db, now_iso

bp = Blueprint('buildings', __name__)


def _load_buildings():
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM buildings
        ORDER BY CASE status
                    WHEN 'closed' THEN 0
                    WHEN 'impaired' THEN 1
                    ELSE 2
                 END, name
        """
    ).fetchall()
    buildings = [dict(r) for r in rows]
    for b in buildings:
        b['is_major'] = bool(b['is_major'])
        b['news_link'] = b['news_link'] or ''

    total = len(buildings)
    closed = sum(1 for b in buildings if b['status'] == 'closed')
    impaired = sum(1 for b in buildings if b['status'] == 'impaired')
    if closed:
        overall = 'critical'
    elif impaired:
        overall = 'impaired'
    else:
        overall = 'healthy'
    return buildings, overall, total, closed, impaired


@bp.route('/')
def index():
    buildings, overall, total, closed, impaired = _load_buildings()
    return render_template(
        'buildings.html',
        buildings=buildings,
        overall_status=overall,
        total=total,
        closed=closed,
        impaired=impaired,
    )


@bp.route('/buildings/suggest', methods=['GET', 'POST'])
@require_login
def suggest():
    db = get_db()
    buildings = db.execute(
        "SELECT id, kuerzel, name FROM buildings ORDER BY name"
    ).fetchall()

    if request.method == 'POST':
        user = current_user()
        kind = request.form.get('kind', 'edit')
        message = (request.form.get('message') or '').strip()

        if kind == 'new':
            payload = {
                'kuerzel': (request.form.get('kuerzel') or '').strip(),
                'name': (request.form.get('name') or '').strip(),
                'adresse': (request.form.get('adresse') or '').strip(),
                'campus': (request.form.get('campus') or '').strip(),
                'status': request.form.get('status') or 'healthy',
                'is_major': bool(request.form.get('is_major')),
                'news_link': (request.form.get('news_link') or '').strip(),
                'workplaces': _int_or_none(request.form.get('workplaces')),
                'size_sqm': _float_or_none(request.form.get('size_sqm')),
                'notes': (request.form.get('notes') or '').strip(),
            }
            if not payload['kuerzel'] or not payload['name']:
                flash('Kürzel und Name sind erforderlich.', 'error')
                return render_template('building_suggest.html', buildings=buildings), 400
            building_id = None
        else:
            try:
                building_id = int(request.form.get('building_id') or 0)
            except ValueError:
                building_id = 0
            if not building_id:
                flash('Bitte ein Gebäude auswählen.', 'error')
                return render_template('building_suggest.html', buildings=buildings), 400
            payload = {
                'status': request.form.get('status') or None,
                'news_link': (request.form.get('news_link') or '').strip() or None,
                'workplaces': _int_or_none(request.form.get('workplaces')),
                'size_sqm': _float_or_none(request.form.get('size_sqm')),
                'notes': (request.form.get('notes') or '').strip() or None,
            }
            payload = {k: v for k, v in payload.items() if v is not None and v != ''}

        db.execute(
            """
            INSERT INTO building_suggestions
                (user_id, building_id, kind, payload, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user['id'], building_id, kind, json.dumps(payload), message or None, now_iso()),
        )
        db.commit()
        flash('Danke! Dein Vorschlag wurde eingereicht.', 'success')
        return redirect(url_for('buildings.index'))

    return render_template('building_suggest.html', buildings=buildings)


def _int_or_none(v):
    if v is None or v == '':
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
