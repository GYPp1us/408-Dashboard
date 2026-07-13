from functools import wraps
import hmac

from flask import jsonify, redirect, render_template, request, session, url_for


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="authentication_required"), 401
        return redirect(url_for("login", next=request.path))

    return wrapped


def register_auth(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            configured = app.config.get("ADMIN_PASSWORD", "")
            if not configured or not hmac.compare_digest(password, configured):
                return render_template("login.html", error="密码错误"), 401
            session.clear()
            session["authenticated"] = True
            return redirect(request.form.get("next") or "/")
        return render_template("login.html", error=None)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
