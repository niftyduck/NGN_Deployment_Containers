from flask import Flask
import requests, os

app = Flask(__name__)
DB_URL = os.environ.get("DB_URL", "http://10.0.0.2:5001")
AUTH_URL = os.environ.get("AUTH_URL")


@app.route("/")
def index():
    try:
        data = requests.get(DB_URL, timeout=2).json()
        html = f"<h1>Web Server</h1><p>Got from DB: {data}</p>"
        if AUTH_URL:
            token = requests.get(AUTH_URL, timeout=2).json()
            html += f"<p>Got from Auth: {token}</p>"
        return html
    except Exception as e:
        return f"<h1>Error connecting to backend</h1><p>{e}</p>", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
