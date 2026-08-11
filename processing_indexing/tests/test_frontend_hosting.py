from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from processing_indexing.frontend_hosting import install_frontend


def test_combined_service_serves_spa_routes_without_swallowing_api_404s(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Aperture launch</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('aperture')", encoding="utf-8")
    app = FastAPI()
    install_frontend(app, dist)
    client = TestClient(app)

    assert client.get("/design").text == "<title>Aperture launch</title>"
    assert client.get("/assets/app.js").text == "console.log('aperture')"
    assert client.get("/api/not-a-route").status_code == 404
