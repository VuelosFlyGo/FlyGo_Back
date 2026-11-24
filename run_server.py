"""Inicia el servidor local de FlyGo sin el recargador de desarrollo."""

from app import app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
