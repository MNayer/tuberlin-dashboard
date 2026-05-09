from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)


def _to_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "ja")


def get_status_data(major_only: bool):
    try:
        df = pd.read_csv('/app/data/status.csv')
        df['is_major'] = df['is_major'].apply(_to_bool)
        df['news_link'] = df['news_link'].fillna('')

        view_df = df[df['is_major']] if major_only else df
        buildings = view_df.to_dict(orient='records')

        total = len(view_df)
        closed = int((view_df['status'] == 'closed').sum())
        impaired = int((view_df['status'] == 'impaired').sum())

        overall_status = "healthy"
        if closed > 0:
            overall_status = "critical"
        elif impaired > 0:
            overall_status = "impaired"

        return buildings, overall_status, total, closed, impaired
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return [], "critical", 0, 0, 0


@app.route('/')
def index():
    major_only = request.args.get('view', 'major') != 'all'
    buildings, overall_status, total, closed, impaired = get_status_data(major_only)
    return render_template('index.html',
                           buildings=buildings,
                           overall_status=overall_status,
                           total=total,
                           closed=closed,
                           impaired=impaired,
                           major_only=major_only)


def create_app():
    return app


if __name__ == '__main__':
    app.run(debug=True)
