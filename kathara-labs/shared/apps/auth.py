from flask import Flask, jsonify
import time

app = Flask(__name__)


@app.route("/")
def login():
    return jsonify({"token": f"fake-jwt-{int(time.time())}", "expires_in": 3600})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
