import os
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import current_user, require_login
from db import get_db, now_iso

bp = Blueprint('reisekosten', __name__)


STATUS_LABELS = {
    'antrag_submitted': 'Antrag eingereicht',
    'antrag_approved': 'Antrag genehmigt',
    'antrag_rejected': 'Antrag abgelehnt',
    'abrechnung_submitted': 'Abrechnung eingereicht',
    'settled': 'Erledigt',
}

OPEN_STATUSES = ('antrag_submitted', 'antrag_approved', 'abrechnung_submitted')


def overdue_months() -> int:
    try:
        return int(os.environ.get('REISEKOSTEN_OVERDUE_MONTHS', '6'))
    except ValueError:
        return 6


def _approx_months_ago(months: int) -> date:
    return date.today() - timedelta(days=months * 30)


def _row_to_dict(row):
    d = dict(row)
    d['status_label'] = STATUS_LABELS.get(d['status'], d['status'])
    d['is_open'] = d['status'] in OPEN_STATUSES
    d['outstanding'] = _outstanding(d)
    d['overdue'] = _is_overdue(d)
    return d


def _outstanding(d):
    if d['status'] in ('antrag_rejected', 'settled'):
        return 0.0
    base = d.get('final_amount')
    if base is None:
        base = d.get('estimated_amount') or 0
    advance = d.get('advance_amount') or 0
    return max(0.0, float(base) - float(advance))


def _is_overdue(d):
    if d['status'] != 'abrechnung_submitted' or not d['abrechnung_date']:
        return False
    try:
        ad = date.fromisoformat(d['abrechnung_date'])
    except (TypeError, ValueError):
        return False
    return ad < _approx_months_ago(overdue_months())


def _dashboard_stats(items):
    open_count = sum(1 for i in items if i['is_open'])
    overdue_count = sum(1 for i in items if i['overdue'])
    outstanding = sum(i['outstanding'] for i in items if i['is_open'])
    return {
        'open_count': open_count,
        'overdue_count': overdue_count,
        'outstanding': outstanding,
        'total': len(items),
    }


@bp.route('/reisekosten')
def index():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM reisekosten ORDER BY datetime(antrag_date) DESC, id DESC"
    ).fetchall()
    items = [_row_to_dict(r) for r in rows]
    stats = _dashboard_stats(items)
    return render_template(
        'reisekosten.html',
        items=items,
        stats=stats,
        overdue_months=overdue_months(),
        status_labels=STATUS_LABELS,
    )


@bp.route('/reisekosten/new', methods=['GET', 'POST'])
@require_login
def new():
    if request.method == 'POST':
        destination = (request.form.get('destination') or '').strip()
        purpose = (request.form.get('purpose') or '').strip() or None
        antrag_date = (request.form.get('antrag_date') or '').strip() or date.today().isoformat()
        travel_start = (request.form.get('travel_start_date') or '').strip() or None
        travel_end = (request.form.get('travel_end_date') or '').strip() or None
        estimated = _float_or_none(request.form.get('estimated_amount'))
        advance = _float_or_none(request.form.get('advance_amount'))

        if not destination:
            flash('Reiseziel ist erforderlich.', 'error')
            return render_template('reisekosten_new.html', form=request.form), 400

        if estimated is not None and advance is None:
            flash('Wenn ein geschätzter Betrag angegeben wird, '
                  'muss auch die Abschlagszahlung angegeben werden (0 falls keine).',
                  'error')
            return render_template('reisekosten_new.html', form=request.form), 400

        user = current_user()
        db = get_db()
        db.execute(
            """
            INSERT INTO reisekosten (
                user_id, destination, purpose, antrag_date,
                travel_start_date, travel_end_date,
                estimated_amount, advance_amount,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'antrag_submitted', ?, ?)
            """,
            (
                user['id'], destination, purpose, antrag_date,
                travel_start, travel_end,
                estimated, advance,
                now_iso(), now_iso(),
            ),
        )
        db.commit()
        flash('Reisekostenantrag eingereicht.', 'success')
        return redirect(url_for('reisekosten.index'))

    return render_template('reisekosten_new.html', form={})


def _float_or_none(v):
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
