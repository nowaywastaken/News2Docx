from news2docx.services.runs import clean_runs, runs_base_dir


def test_runs_base_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "myruns"))
    base = runs_base_dir()
    assert str(base).endswith("myruns")


def test_clean_runs(tmp_path):
    base = tmp_path / "runs"
    (base / "r1").mkdir(parents=True)
    (base / "r2").mkdir(parents=True)
    # Ensure r1 is older
    (base / "r1").touch()
    (base / "r2").touch()
    deleted = clean_runs(base, keep=1)
    # Only one should be deleted
    assert len(deleted) == 1
    assert (base / "r1").exists() ^ (base / "r2").exists()
