from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG =================
CFG = {
    "tps_range": (90, 105),
    "lambda_range": (0.80, 0.92),
    "fuel_range": (317, 372),
    "ambient_offset": 15,
    "cheat_delay_sec": 0.5
}

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= HTML =================
HTML = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Boat Data Analyzer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4 bg-dark text-light">
<div class="container">

<div class="d-flex justify-content-between align-items-center mb-4">
  <img src="{{ url_for('static', filename='precision_logo.png') }}" style="height:120px;">
  <h1 class="text-center flex-grow-1">{{ etat_global }}</h1>
  <img src="{{ url_for('static', filename='image_copy.png') }}" style="height:120px;">
</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-2">
  <div class="col"><input class="form-control" type="date" name="date_test"></div>
  <div class="col"><input class="form-control" type="time" name="heure_session"></div>
  <div class="col"><input class="form-control" name="num_embarcation" placeholder="Numéro embarcation"></div>
</div>

<div class="row mb-3">
  <div class="col-md-4">
    <input class="form-control" type="number" step="0.1" name="ambient_temp"
           placeholder="Température ambiante (°C)" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr>
<a class="btn btn-success" href="{{ download }}">Télécharger CSV</a>
<div class="table-responsive mt-3">{{ table|safe }}</div>
{% endif %}

</div>
</body>
</html>
"""

# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    df = df.copy()

    # ---------- TPS ----------
    tps_col = [c for c in df.columns if "TPS" in c.upper()]
    if tps_col:
        df["TPS_OK"] = df[tps_col[0]].between(*CFG["tps_range"])
    else:
        df["TPS_OK"] = True

    # ---------- LAMBDA (AUTO-DETECTION) ----------
    lambda_cols = [c for c in df.columns if "LAMBDA" in c.upper() or "AFR" in c.upper()]

    if lambda_cols:
        df["Lambda"] = df[lambda_cols].mean(axis=1)
        df["Lambda_OK"] = df["Lambda"].between(*CFG["lambda_range"])
    else:
        df["Lambda_OK"] = True

    # ---------- FUEL ----------
    fuel_cols = [c for c in df.columns if "FUEL" in c.upper() and "PRESS" in c.upper()]
    if fuel_cols:
        df["Fuel_OK"] = df[fuel_cols[0]].between(*CFG["fuel_range"])
    else:
        df["Fuel_OK"] = True

    # ---------- TEMP ----------
    if "IAT (°C)" in df.columns:
        df["IAT_OK"] = df["IAT (°C)"] <= ambient_temp + CFG["ambient_offset"]
    else:
        df["IAT_OK"] = True

    if "ECT (°C)" in df.columns:
        df["ECT_OK"] = df["ECT (°C)"] <= ambient_temp + CFG["ambient_offset"]
    else:
        df["ECT_OK"] = True

    # ---------- OUT RAW ----------
    df["OUT_RAW"] = ~(df["TPS_OK"] & df["Lambda_OK"] & df["Fuel_OK"] & df["IAT_OK"] & df["ECT_OK"])

    # ---------- TEMPS ----------
    if "Time (s)" in df.columns:
        df["dt"] = df["Time (s)"].diff().fillna(0)
    else:
        df["dt"] = 0

    # ---------- DELAI ANTI SPOT ----------
    cum = 0.0
    debut = []

    for out, dt in zip(df["OUT_RAW"], df["dt"]):
        if out:
            cum += dt
            debut.append(cum >= CFG["cheat_delay_sec"])
        else:
            cum = 0
            debut.append(False)

    df["Début_triche"] = debut
    df["QUALIFIÉ"] = ~(df["OUT_RAW"].rolling(2).max().fillna(0).astype(bool))

    return df

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(HTML, table=None, download=None, etat_global="Boat Data Analyzer")

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    ambient_temp = float(request.form["ambient_temp"])

    df = pd.read_csv(file)
    df = analyze_dataframe(df, ambient_temp)

    cheat_time = None
    if "Time (s)" in df.columns:
        rows = df[df["Début_triche"]]
        if not rows.empty:
            cheat_time = rows["Time (s)"].iloc[0]

    etat = "PASS" if cheat_time is None else f"CHEAT – Début à {cheat_time:.2f} s"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)
    df.to_csv(path, index=False)

    table = df.head(100).to_html(classes="table table-dark table-striped", index=False)

    return render_template_string(
        HTML,
        table=table,
        download=url_for("download", fname=fname),
        etat_global=etat
    )

@app.route("/download")
def download():
    fname = request.args.get("fname")
    return send_file(os.path.join(UPLOAD_DIR, fname), as_attachment=True)

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5002)


