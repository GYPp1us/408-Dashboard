from functools import wraps
import re
import sqlite3
from datetime import datetime, timezone

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import claim_invitation, connect, create_user, get_user, get_user_by_identifier


def is_guest() -> bool:
    return session.get("role") == "guest" or bool(session.get("viewing_as_guest"))


def current_user_id() -> int | None:
    value = session.get("user_id")
    return int(value) if value is not None else None


def current_user(connection) -> dict | None:
    return get_user(connection, current_user_id())


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="authentication_required"), 401
        return redirect(url_for("login", next=request.path))

    return wrapped


def user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated") and is_guest():
            if request.path.startswith("/api/"):
                return jsonify(error="guest_read_only"), 403
            return redirect(url_for("guest_dashboard"))
        if not session.get("authenticated") or current_user_id() is None:
            if request.path.startswith("/api/"):
                return jsonify(error="authentication_required"), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

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
        if session.get("role") != "site_owner":
            if request.path.startswith("/api/"):
                return jsonify(error="site_owner_required"), 403
            return redirect(url_for("user_dashboard", username=session.get("username", "")))
        return view(*args, **kwargs)

    return wrapped


owner_required = admin_required


def register_auth(app):
    @app.context_processor
    def inject_auth_user():
        user_id = current_user_id()
        if user_id is None:
            return {"auth_user": None}
        connection = connect(app.config["DATABASE"])
        try:
            return {"auth_user": current_user(connection)}
        finally:
            connection.close()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip() or app.config.get("ADMIN_USERNAME", "admin")
            password = request.form.get("password", "")
            connection = connect(app.config["DATABASE"])
            try:
                user = get_user_by_identifier(connection, identifier)
            finally:
                connection.close()
            if not user or not check_password_hash(user["password_hash"], password):
                return render_template("login.html", error="用户名或密码错误"), 401
            session.clear()
            session.update(authenticated=True, role=user["role"], user_id=user["id"], username=user["username"])
            next_url = request.form.get("next") or url_for("user_dashboard", username=user["username"])
            return redirect(next_url if next_url.startswith("/") else "/")
        return render_template("login.html", error=None)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        code = request.args.get("code", "").strip() if request.method == "GET" else request.form.get("invite_code", "").strip()
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,24}", username):
                return render_template("register.html", error="用户名需为 2-24 位中文、字母、数字、下划线或短横线", code=code), 400
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                return render_template("register.html", error="请输入格式正确的邮箱", code=code), 400
            if len(password) < 8:
                return render_template("register.html", error="密码至少需要 8 位", code=code), 400
            connection = connect(app.config["DATABASE"])
            try:
                invitation = connection.execute("SELECT id FROM invitations WHERE code = ? AND used_by IS NULL", (code,)).fetchone()
                if not invitation:
                    return render_template("register.html", error="邀请码无效或已使用", code=code), 400
                user_id = create_user(connection, username, email, generate_password_hash(password), datetime.now(timezone.utc).isoformat())
                if not claim_invitation(connection, code, user_id, datetime.now(timezone.utc).isoformat()):
                    connection.rollback()
                    return render_template("register.html", error="邀请码刚刚被使用，请重新获取", code=code), 409
                connection.commit()
                user = get_user(connection, user_id)
            except sqlite3.IntegrityError:
                connection.rollback()
                return render_template("register.html", error="用户名或邮箱已存在", code=code), 409
            finally:
                connection.close()
            session.clear()
            session.update(authenticated=True, role=user["role"], user_id=user["id"], username=user["username"])
            return redirect(url_for("user_dashboard", username=user["username"]))
        return render_template("register.html", error=None, code=code)

    @app.get("/admin")
    def switch_admin():
        if session.get("authenticated") and session.get("role") == "site_owner":
            return redirect(url_for("user_dashboard", username=session.get("username", "")))
        return redirect(url_for("login", next=url_for("switch_admin")))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("guest_dashboard"))
