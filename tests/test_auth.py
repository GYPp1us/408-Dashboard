import pytest


@pytest.fixture()
def client(tmp_path):
    from app import create_app

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "auth.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    })
    return app.test_client()


def test_root_redirects_to_guest_without_password(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/guest")
    guest = client.get(response.headers["Location"])
    assert guest.status_code == 200
    assert 'data-role="guest"' in guest.get_data(as_text=True)
    assert client.get("/api/dashboard").status_code == 200


def test_invalid_password_is_rejected(client):
    response = client.post("/login", data={"password": "wrong"})

    assert response.status_code == 401
    assert "密码错误" in response.get_data(as_text=True)


def test_successful_login_sets_cookie_and_redirects(client):
    response = client.post("/login", data={"password": "test-password"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_logout_clears_authenticated_session(client):
    client.post("/login", data={"password": "test-password"})
    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/guest")
    assert client.get("/admin").headers["Location"].startswith("/login?")


def test_guest_dashboard_needs_no_password_and_admin_switch_requires_login(client):
    response = client.get("/guest")

    assert response.status_code == 200
    assert client.get("/api/dashboard").status_code == 200
    admin_switch = client.get("/admin")
    assert admin_switch.status_code == 302
    assert admin_switch.headers["Location"].startswith("/login?")

    login = client.post("/login", data={"password": "test-password", "next": "/admin"})
    assert login.headers["Location"].endswith("/admin")
    assert client.get("/admin").headers["Location"].endswith("/")
    assert 'data-role="admin"' in client.get("/").get_data(as_text=True)


def test_entering_guest_clears_admin_authentication(client):
    client.post("/login", data={"password": "test-password"})

    assert client.get("/guest").status_code == 200
    response = client.get("/admin")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?")
