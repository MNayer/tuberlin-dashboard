from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

def get_status_data():
    try:
        # Note: Ensure this path exists in your environment/container
        df = pd.read_csv('/app/data/status.csv')
        buildings = df.to_dict(orient='records')

        total = len(buildings)
        closed = len(df[df['status'] == 'closed'])
        impaired = len(df[df['status'] == 'impaired'])

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
    buildings, overall_status, total, closed, impaired = get_status_data()
    return render_template('index.html',
                           buildings=buildings,
                           overall_status=overall_status,
                           total=total,
                           closed=closed,
                           impaired=impaired)

def create_app():
    return app

if __name__ == '__main__':
    app.run(debug=True)
