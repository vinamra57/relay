import csv
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "vitals" / "bidmc_01_Numerics.csv"


def load_demo_vitals() -> list[dict]:
    """Load a small vitals dataset for demo playback."""
    if not DATA_PATH.exists():
        return []

    series: list[dict] = []
    with DATA_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                hr = float(row.get("HR", ""))
                resp = float(row.get("RESP", ""))
                spo2 = float(row.get("SpO2", ""))
            except ValueError:
                continue
            series.append({
                "hr": hr,
                "resp": resp,
                "spo2": spo2,
            })

    return series


class VitalsSequence:
    def __init__(self, series: list[dict]):
        self.series = series
        self.idx = 0

    def next(self) -> dict | None:
        if not self.series:
            return None
        value = self.series[self.idx]
        self.idx = (self.idx + 1) % len(self.series)
        return value
