#!/usr/bin/env python3
"""Print the transcript for the most recent session (or a specific session_id)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.models.session import SessionArtifact, Session as DrillSession

settings = get_settings()
engine = create_engine(settings.database_url)

session_id = sys.argv[1] if len(sys.argv) > 1 else None

with DbSession(engine) as db:
    if not session_id:
        latest = db.scalar(select(DrillSession).order_by(desc(DrillSession.started_at)))
        if not latest:
            print("No sessions found.")
            sys.exit(1)
        session_id = latest.id
        print(f"Most recent session: {session_id}\n")

    artifact = db.scalar(
        select(SessionArtifact).where(
            SessionArtifact.session_id == session_id,
            SessionArtifact.artifact_type == "canonical_transcript",
        )
    )

    if not artifact or not artifact.metadata_json:
        print(f"No transcript found for session {session_id}")
        sys.exit(1)

    turns = artifact.metadata_json.get("transcript", [])
    if not turns:
        print("Transcript is empty.")
        sys.exit(0)

    print(f"{'─'*60}")
    for t in turns:
        speaker = "REP      " if t['speaker'] == 'rep' else "HOMEOWNER"
        stage = f"[{t['stage']}]" if t.get('stage') else ""
        print(f"{speaker} {stage}")
        print(f"  \"{t['text']}\"")
        if t.get('objection_tags'):
            print(f"  objections: {t['objection_tags']}")
        print()
    print(f"{'─'*60}")
    print(f"Total turns: {len(turns)}")
