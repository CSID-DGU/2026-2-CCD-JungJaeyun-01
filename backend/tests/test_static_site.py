from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_site import mount_frontend


def make_app(tmp_path, with_dist=True):
    dist = tmp_path / "dist"
    if with_dist:
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>APP</html>", encoding="utf-8")
        (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    mounted = mount_frontend(app, dist)
    return app, mounted


def test_serves_app_assets_and_root_files(tmp_path):
    app, mounted = make_app(tmp_path)
    c = TestClient(app)
    assert mounted
    assert c.get("/").text == "<html>APP</html>"
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/some/deep/link?s=abc").text == "<html>APP</html>"  # 새로고침·공유 링크


def test_api_routes_win_and_unknown_api_paths_are_404_not_the_app(tmp_path):
    app, _ = make_app(tmp_path)
    c = TestClient(app)
    assert c.get("/api/ping").json() == {"ok": True}
    assert c.get("/api/nope").status_code == 404
    assert c.get("/auth/nope").status_code == 404


def test_cannot_read_files_outside_the_dist_folder(tmp_path):
    app, _ = make_app(tmp_path)
    c = TestClient(app)
    assert c.get("/..%2Fsecret.txt").text == "<html>APP</html>"
    assert "nope" not in c.get("/../secret.txt").text


def test_nothing_is_registered_without_a_build(tmp_path):
    app, mounted = make_app(tmp_path, with_dist=False)
    assert not mounted and TestClient(app).get("/").status_code == 404
