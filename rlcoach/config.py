import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator


class ThresholdConfig(BaseModel):
    slow_recovery_s: float = 3.0
    double_commit_min_duration_s: float = 1.0
    file_stable_wait_s: float = 3.0
    kickoff_concede_window_s: float = 10.0


class AppConfig(BaseModel):
    output_dir: Path
    player_id: str
    poll_interval_s: int = 2700          # 45 minutes, like rockpload
    player_display_name: Optional[str] = None
    thresholds: ThresholdConfig = ThresholdConfig()
    # Legacy: kept so old config.yaml files don't break, but not used in API mode
    input_dir: Optional[Path] = None

    @field_validator("input_dir", "output_dir", mode="before")
    @classmethod
    def expand_path(cls, v) -> Optional[Path]:
        if v is None:
            return None
        return Path(os.path.expandvars(str(v))).expanduser()


def load_config(path: Path = Path("config.yaml")) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)
