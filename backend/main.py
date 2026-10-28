"""
IPL Auction Analytics API
FastAPI backend for the IPL auction analysis dashboard.
Dataset is loaded from IPLDataset.csv beside this file by default.
Set IPL_DATA_PATH to override the CSV location.
"""
from __future__ import annotations
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

import boto3
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
S3_BUCKET = os.getenv("IPL_S3_BUCKET", "ipl-auction-analytics-data-2026")
S3_KEY = os.getenv("IPL_S3_KEY", "IPLDataset.csv")
DATA_PATH = Path(os.getenv("IPL_DATA_PATH", str(BASE_DIR / "IPLDataset.csv")))

REQUIRED_COLUMNS = [
    "Player Name", "Team", "Nationality", "Player_Type", "Capped",
    "Matches_Played", "Runs", "Average", "Strike_Rate", "Wickets",
    "Bowling_average", "Economy", "Bowling_Strike_Rate", "Catches",
    "Run_outs", "Stumps",
]

app = FastAPI(
    title="IPL Auction Analytics API",
    description="Explore player statistics, team summaries, and a data-driven best XI.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to your frontend origin when deploying publicly.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
def load_dataset() -> pd.DataFrame:
    """Load the dataset from private S3, or from a configured local CSV."""
    if os.getenv("IPL_DATA_PATH"):
        frame = pd.read_csv(DATA_PATH)
    else:
        response = boto3.client("s3").get_object(
            Bucket=S3_BUCKET, Key=S3_KEY
        )
        frame = pd.read_csv(BytesIO(response["Body"].read()))

    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise RuntimeError(f"CSV is missing required columns: {', '.join(missing)}")

    defaults = {
        "Player Name": "",
        "Team": "Unknown",
        "Nationality": "Unknown",
        "Player_Type": "Unknown",
    }
    for column, default in defaults.items():
        frame[column] = frame[column].fillna(default).astype(str).str.strip()

    for column in REQUIRED_COLUMNS:
        if column not in defaults:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)

    return frame.loc[frame["Player Name"] != ""].reset_index(drop=True)
try:
    DATA = load_dataset()
    DATA_ERROR = None
except Exception as exc:
    DATA = pd.DataFrame(columns=REQUIRED_COLUMNS)
    DATA_ERROR = str(exc)

def require_data() -> pd.DataFrame:
    if DATA_ERROR or DATA.empty:
        raise HTTPException(status_code=503, detail=DATA_ERROR or "Dataset is empty.")
    return DATA.copy()

def serialize_records(frame: pd.DataFrame) -> list[dict]:
    safe = frame.copy()
    safe = safe.where(pd.notna(safe), None)
    return safe.to_dict(orient="records")

def capped(frame: pd.DataFrame) -> pd.DataFrame:
    # Mirrors the source notebook's capped-player filtering (Capped == 1).
    return frame.loc[frame["Capped"] == 1].copy()

@app.get("/")
def root():
    return {"message": "IPL Auction Analytics API", "docs": "/docs", "health": "/api/health"}

@app.get("/api/health")
def health():
    return {
        "status": "ok" if DATA_ERROR is None and not DATA.empty else "dataset_error",
        "dataset_rows": int(len(DATA)),
        "dataset_path": os.getenv("IPL_DATA_PATH", f"s3://{S3_BUCKET}/{S3_KEY}"),
        "error": DATA_ERROR,
    }

@app.get("/api/summary")
def summary():
    frame = require_data()
    return {
        "total_players": int(len(frame)),
        "teams": int(frame["Team"].nunique()),
        "capped_players": int((frame["Capped"] == 1).sum()),
        "player_types": {str(k): int(v) for k, v in frame["Player_Type"].value_counts().items()},
        "nationalities": {str(k): int(v) for k, v in frame["Nationality"].value_counts().items()},
        "top_runs": serialize_records(frame.sort_values("Runs", ascending=False).head(5)[
            ["Player Name", "Team", "Player_Type", "Runs", "Average", "Strike_Rate"]]),
        "top_wickets": serialize_records(frame.sort_values("Wickets", ascending=False).head(5)[
            ["Player Name", "Team", "Player_Type", "Wickets", "Economy", "Bowling_average"]]),
    }

@app.get("/api/teams")
def teams():
    frame = require_data()
    result = []
    for team, group in frame.groupby("Team", dropna=False):
        result.append({
            "team": str(team),
            "players": int(len(group)),
            "capped_players": int((group["Capped"] == 1).sum()),
            "runs": int(group["Runs"].sum()),
            "wickets": int(group["Wickets"].sum()),
            "average_player_runs": round(float(group["Runs"].mean()), 2),
        })
    return sorted(result, key=lambda item: item["players"], reverse=True)

@app.get("/api/players")
def players(
    search: Optional[str] = Query(default=None, description="Search player, team, or nationality"),
    player_type: Optional[str] = Query(default=None, alias="type"),
    team: Optional[str] = None,
    capped_only: bool = False,
    sort_by: str = "Runs",
    order: str = "desc",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    frame = require_data()
    if search:
        needle = search.strip().lower()
        mask = (
            frame["Player Name"].str.lower().str.contains(needle, regex=False)
            | frame["Team"].str.lower().str.contains(needle, regex=False)
            | frame["Nationality"].str.lower().str.contains(needle, regex=False)
        )
        frame = frame.loc[mask]
    if player_type and player_type.lower() != "all":
        frame = frame.loc[frame["Player_Type"].str.lower() == player_type.lower()]
    if team and team.lower() != "all":
        frame = frame.loc[frame["Team"].str.lower() == team.lower()]
    if capped_only:
        frame = frame.loc[frame["Capped"] == 1]
    allowed_sort = set(REQUIRED_COLUMNS) - {"Player Name", "Team", "Nationality", "Player_Type"}
    if sort_by not in REQUIRED_COLUMNS:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of: {', '.join(REQUIRED_COLUMNS)}")
    ascending = order.lower() == "asc"
    frame = frame.sort_values(sort_by, ascending=ascending, kind="stable")
    total = int(len(frame))
    page = frame.iloc[offset:offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "players": serialize_records(page)}

@app.get("/api/best-xi")
def best_xi():
    """
    Build a suggested XI using the notebook's 3 Batter / 3 Allrounder /
    4 Bowler / 1 Keeper structure. This is a transparent heuristic, not
    an official auction valuation or a trained predictive model.
    """
    frame = capped(require_data())
    picks = []

    batters = frame[(frame["Player_Type"] == "Batter") & (frame["Average"] >= 30.0)]
    batters = batters.sort_values(["Runs", "Average", "Strike_Rate"], ascending=False).head(3)
    picks.extend((row, "Batter", "Runs, average and strike rate") for _, row in batters.iterrows())

    allrounders = frame[(frame["Player_Type"] == "Allrounder") & (frame["Average"] >= 25.0)].copy()
    allrounders["_score"] = allrounders["Runs"] / max(float(allrounders["Runs"].max()), 1) + \
                            allrounders["Wickets"] / max(float(allrounders["Wickets"].max()), 1)
    allrounders = allrounders.sort_values(["_score", "Runs", "Wickets"], ascending=False).head(3)
    picks.extend((row, "Allrounder", "Combined batting runs and wickets") for _, row in allrounders.iterrows())

    bowlers = frame[frame["Player_Type"] == "Bowler"].copy()
    bowlers = bowlers.sort_values(["Wickets", "Economy", "Bowling_average"], ascending=[False, True, True]).head(4)
    picks.extend((row, "Bowler", "Wickets, then economy and bowling average") for _, row in bowlers.iterrows())

    keepers = frame[(frame["Player_Type"] == "Keeper") & (frame["Average"] >= 25.0)]
    keepers = keepers.sort_values(["Runs", "Average", "Strike_Rate"], ascending=False).head(1)
    picks.extend((row, "Keeper", "Runs, average and strike rate") for _, row in keepers.iterrows())

    output = []
    for row, slot, reason in picks:
        record = {key: row[key] for key in REQUIRED_COLUMNS}
        record["XI_Role"] = slot
        record["Selection_Basis"] = reason
        output.append(record)
    return {
        "formation": "3 Batters · 3 Allrounders · 4 Bowlers · 1 Keeper",
        "selected": len(output),
        "target": 11,
        "note": "Suggested from the supplied dataset using simple ranking rules; not an official or predictive team selection.",
        "players": serialize_records(pd.DataFrame(output)) if output else [],
    }

# Serve the static HTML/CSS/JS when the frontend folder is present.
FRONTEND_DIR = BASE_DIR.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

from fastapi.responses import FileResponse

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(index_file)
