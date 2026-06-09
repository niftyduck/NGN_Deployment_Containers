from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def data():
    return jsonify({"rows": ["user_1", "user_2", "user_3"], "count": 3})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
