import os
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from auth import current_user, require_login
from db import get_db, now_iso

bp = Blueprint('reisekosten', __name__)


STATUS_LABELS = {
    'submitted': 'Eingereicht',
    'settled': 'Erstattet',
}


def overdue_months() -> int:
    try:
        return int(os.environ.get('REISEKOSTEN_OVERDUE_MONTHS', '6'))
    except ValueError:
        return 6


def _overdue_days() -> int:
    return overdue_months() * 30


def _row_to_dict(row, user_id=None):
    d = dict(row)
    d['status_label'] = STATUS_LABELS.get(d['status'], d['status'])
    d['is_open'] = d['status'] != 'settled'
    d['outstanding'] = _outstanding(d)
    d['overdue'] = _is_overdue(d)
    d['processing_days'] = _processing_days(d)
    d['is_mine'] = (user_id is not None and d.get('user_id') == user_id)
    return d


def _outstanding(d):
    if d['status'] == 'settled':
        return 0.0
    amount = d.get('amount') or 0
    advance = d.get('advance_amount') or 0
    return max(0.0, float(amount) - float(advance))


def _parse_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _is_overdue(d):
    ad = _parse_date(d.get('antrag_date'))
    if not ad:
        return False
    if d['status'] == 'settled':
        ed = _parse_date(d.get('erstattungsdatum'))
        if not ed:
            return False
        return (ed - ad).days > _overdue_days()
    return (date.today() - ad).days > _overdue_days()


def _processing_days(d):
    if d['status'] != 'settled':
        return None
    ad = _parse_date(d.get('antrag_date'))
    ed = _parse_date(d.get('erstattungsdatum'))
    if not ad or not ed:
        return None
    return (ed - ad).days


def _dashboard_stats(items):
    open_count = sum(1 for i in items if i['is_open'])
    overdue_count = sum(1 for i in items if i['overdue'])
    outstanding = sum(i['outstanding'] for i in items if i['is_open'])
    durations = [i['processing_days'] for i in items if i['processing_days'] is not None]
    avg_days = (sum(durations) / len(durations)) if durations else None
    return {
        'total': len(items),
        'open_count': open_count,
        'overdue_count': overdue_count,
        'outstanding': outstanding,
        'avg_processing_days': avg_days,
    }


def _parse_form(form):
    return {
        'destination': (form.get('destination') or '').strip(),
        'antrag_date': (form.get('antrag_date') or '').strip(),
        'amount': _float_or_none(form.get('amount')),
        'advance_amount': _float_or_none(form.get('advance_amount')),
        'erstattungsdatum': (form.get('erstattungsdatum') or '').strip() or None,
    }


def _validate(data):
    if not data['destination']:
        return 'Reiseziel ist erforderlich.'
    if not data['antrag_date']:
        return 'Datum des Erstattungsantrags ist erforderlich.'
    if data['amount'] is not None and data['advance_amount'] is None:
        return ('Wenn Kosten angegeben werden, muss auch die Abschlagszahlung '
                'angegeben werden (0 falls keine).')
    return None


@bp.route('/reisekosten')
def index():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM reisekosten ORDER BY datetime(antrag_date) DESC, id DESC"
    ).fetchall()
    uid = session.get('user_id')
    items = [_row_to_dict(r, user_id=uid) for r in rows]
    stats = _dashboard_stats(items)
    return render_template(
        'reisekosten.html',
        items=items,
        stats=stats,
        overdue_months=overdue_months(),
        status_labels=STATUS_LABELS,
        logged_in=bool(uid),
    )


@bp.route('/reisekosten/new', methods=['GET', 'POST'])
@require_login
def new():
    if request.method == 'POST':
        data = _parse_form(request.form)
        err = _validate(data)
        if err:
            flash(err, 'error')
            return render_template('reisekosten_form.html', form=data, mode='new'), 400

        status = 'settled' if data['erstattungsdatum'] else 'submitted'
        user = current_user()
        db = get_db()
        db.execute(
            """
            INSERT INTO reisekosten (
                user_id, destination, antrag_date,
                amount, advance_amount, erstattungsdatum,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user['id'], data['destination'], data['antrag_date'],
                data['amount'], data['advance_amount'], data['erstattungsdatum'],
                status, now_iso(), now_iso(),
            ),
        )
        db.commit()
        flash('Erstattungsantrag erfasst.', 'success')
        return redirect(url_for('reisekosten.index'))

    return render_template('reisekosten_form.html', form={'antrag_date': date.today().isoformat()}, mode='new')


@bp.route('/reisekosten/<int:rid>/edit', methods=['GET', 'POST'])
@require_login
def edit(rid):
    user = current_user()
    db = get_db()
    row = db.execute("SELECT * FROM reisekosten WHERE id = ?", (rid,)).fetchone()
    if not row:
        abort(404)
    if row['user_id'] != user['id']:
        abort(403)

    if request.method == 'POST':
        data = _parse_form(request.form)
        err = _validate(data)
        if err:
            flash(err, 'error')
            return render_template('reisekosten_form.html', form=data, mode='edit', rid=rid), 400

        status = 'settled' if data['erstattungsdatum'] else 'submitted'
        db.execute(
            """
            UPDATE reisekosten SET
                destination = ?, antrag_date = ?,
                amount = ?, advance_amount = ?, erstattungsdatum = ?,
                status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data['destination'], data['antrag_date'],
                data['amount'], data['advance_amount'], data['erstattungsdatum'],
                status, now_iso(), rid,
            ),
        )
        db.commit()
        flash('Erstattungsantrag aktualisiert.', 'success')
        return redirect(url_for('reisekosten.index'))

    return render_template('reisekosten_form.html', form=dict(row), mode='edit', rid=rid)


def _float_or_none(v):
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
