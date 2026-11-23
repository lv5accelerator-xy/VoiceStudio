"""Real Demucs separation through the production API.

The trained HTDemucs checkpoint is large and licensed separately, so this
builds a tiny randomly initialized HTDemucs in the same package format. Output
quality is meaningless; the test proves the CLI flags, repository mode, device
selection, stem names and file moves that the real checkpoint goes through.
"""

import pytest

from services.music import production as production_service
from test_music_production import settle, workbench  # noqa: F401  (shared fixture)

demucs_htdemucs = pytest.importorskip("demucs.htdemucs")
demucs_states = pytest.importorskip("demucs.states")
omegaconf = pytest.importorskip("omegaconf")
torch = pytest.importorskip("torch")
soundfile = pytest.importorskip("soundfile")

FAKE_WEIGHT = "955717e8.th"  # no checksum suffix: the random model cannot match the real hash


@pytest.fixture
def tiny_demucs(workbench, monkeypatch):  # noqa: F811
    _, _, _, data = workbench
    models = data / "models"
    models.mkdir()
    model = demucs_htdemucs.HTDemucs(
        sources=["drums", "bass", "other", "vocals"], channels=8, depth=4,
        t_layers=1, bottom_channels=0, samplerate=44100, segment=4,
    )
    torch.save(demucs_states.serialize_model(model, omegaconf.OmegaConf.create({}), half=False),
               models / FAKE_WEIGHT)
    monkeypatch.setattr(production_service, "WEIGHT", FAKE_WEIGHT)
    monkeypatch.setattr(production_service, "local_weight", lambda: models / FAKE_WEIGHT)
    monkeypatch.setattr(production_service, "demucs_device", lambda: "cpu")
    return workbench


@pytest.mark.parametrize(("mode", "stems"), [
    ("two", ["vocals", "accompaniment"]),
    ("four", ["vocals", "drums", "bass", "other"]),
])
def test_real_demucs_separation_produces_named_stems(tiny_demucs, mode, stems):
    client, url, asset, data = tiny_demucs
    result = client.post(url + "/production", json={"audioId": asset, "separation": mode, "renderVideo": False})
    assert result.status_code == 202, result.text
    run = settle(client, url, result.json()["id"])
    assert run["state"] == "done", run
    assert run["completed"] == ["inputs", "stems", "mix", "export"]
    assert [name for name in run["artifacts"] if name.endswith(".wav")] == [*(f"{stem}.wav" for stem in stems), "mix.wav"]
    run_dir = data / "music" / "production" / url.rsplit("/", 1)[1] / run["id"]
    for stem in stems:
        info = soundfile.info(str(run_dir / f"{stem}.wav"))
        assert info.channels == 2 and info.samplerate == 44100 and info.subtype == "FLOAT"
        assert info.frames > 40000  # the one-second source survives separation
    assert not [path for path in run_dir.iterdir() if path.is_dir()]  # Demucs scratch removed


def test_failed_gpu_separation_retries_on_cpu(tiny_demucs, monkeypatch):
    client, url, asset, _ = tiny_demucs
    calls = []
    original = production_service.run_child

    async def flaky_child(job, cmd, error, **kwargs):
        device = cmd[cmd.index("-d") + 1]
        calls.append((device, "--segment" in cmd))
        if device == "cuda":
            raise production_service.MusicError(error, 422)
        await original(job, cmd, error, **kwargs)

    monkeypatch.setattr(production_service, "demucs_device", lambda: "cuda")
    monkeypatch.setattr(production_service, "run_child", flaky_child)
    result = client.post(url + "/production", json={"audioId": asset, "separation": "two", "renderVideo": False})
    run = settle(client, url, result.json()["id"])
    assert run["state"] == "done", run
    assert calls == [("cuda", False), ("cpu", True)]


def test_demucs_failure_logs_its_diagnostics(tiny_demucs, caplog):
    client, url, asset, data = tiny_demucs
    (data / "models" / FAKE_WEIGHT).write_bytes(b"not a model")
    result = client.post(url + "/production", json={"audioId": asset, "separation": "two", "renderVideo": False})
    run = settle(client, url, result.json()["id"])
    assert (run["state"], run["error"]) == ("failed", "demucs_failed")
    logged = [record.getMessage() for record in caplog.records if "demucs_failed exited" in record.getMessage()]
    assert logged and "Traceback" in logged[0]
