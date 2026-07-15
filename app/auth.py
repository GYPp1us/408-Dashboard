from functools import wraps
import hmac

from flask import jsonify, redirect, render_template, request, session, url_for


def is_guest() -> bool:
    return session.get("role") == "guest"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="authentication_required"), 401
        return redirect(url_for("login", next=request.path))

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify(error="authentication_required"), 401
            return redirect(url_for("login", next=request.path))
        if is_guest():
            if request.path.startswith("/api/"):
                return jsonify(error="guest_read_only"), 403
            return redirect(url_for("guest_dashboard"))
        return view(*args, **kwargs)

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
            session["role"] = "admin"
            return redirect(request.form.get("next") or "/")
        return render_template("login.html", error=None)

    @app.get("/admin")
    def switch_admin():
        if session.get("authenticated") and not is_guest():
            return redirect(url_for("dashboard"))
        return redirect(url_for("login", next=url_for("switch_admin")))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("guest_dashboard"))
