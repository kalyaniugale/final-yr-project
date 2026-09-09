"""Independent expert review interface. Run: streamlit run app/expert_review.py

Reviewers must judge the evidence, not the MCDA score. No automatic labels.
"""
from __future__ import annotations
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from review_queue import prepare, QUEUE, LABELS, OUT
OUT=ROOT/"reports/expert_review"
QUEUE=OUT/"review_queue.csv"
LABELS=OUT/"expert_labels.csv"
SCALE={0:"0 — Unsuitable",1:"1 — Low suitability",2:"2 — Moderate",
       3:"3 — Good",4:"4 — Very good"}
FIELDS=["pair_id","vendor_profile_id","business_category","preferred_division",
        "zone_id","reviewer_id","reviewed_at_utc","relevance","recommendation",
        "confidence","reason","evidence_version"]

st.set_page_config(page_title="Nashik Expert Review",layout="wide")
st.title("Independent vendor–zone review")
st.caption("Research labeling only. This tool does not issue vending permits or verify live vacancy.")

def safe_read(path):
    return pd.read_csv(path,dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=FIELDS)

def write_label(record):
    labels=safe_read(LABELS)
    key=(labels.pair_id.eq(record["pair_id"]) &
         labels.reviewer_id.eq(record["reviewer_id"])) if len(labels) else pd.Series(dtype=bool)
    if key.any():
        raise ValueError("This reviewer already submitted this pair. Use a new review version if revisions are required.")
    updated=pd.concat([labels,pd.DataFrame([record])],ignore_index=True)
    temp=LABELS.with_suffix(".tmp")
    updated.to_csv(temp,index=False,encoding="utf-8-sig")
    temp.replace(LABELS)

try:
    queue=prepare()
except Exception as exc:
    st.error(str(exc))
    st.stop()
labels=safe_read(LABELS)
with st.sidebar:
    reviewer=st.text_input("Reviewer ID",placeholder="EXPERT_01")
    st.caption("Use a distinct ID for each independent reviewer. Keep the ID private to the research team.")
    st.write("Queue pairs:",len(queue))
    st.write("Saved judgments:",len(labels))
    if LABELS.exists():
        st.download_button("Export expert labels",LABELS.read_bytes(),
                           file_name="expert_labels.csv",mime="text/csv")
if not reviewer.strip():
    st.info("Enter your reviewer ID to begin.")
    st.stop()
done=set(labels.loc[labels.reviewer_id.eq(reviewer.strip()),"pair_id"])
pending=queue.loc[~queue.pair_id.isin(done)]
if pending.empty:
    st.success("All assigned pairs have been reviewed.")
    st.stop()
idx=st.selectbox("Review pair",pending.index.tolist(),
    format_func=lambda i:f"{queue.loc[i,'business_category']} — {queue.loc[i,'zone_id']}")
r=queue.loc[idx]
st.subheader(f"{r.business_category.replace('_',' ').title()} → {r.zone_id}")
st.write("Preferred division:",r.preferred_division)
st.write("Official zone description:",r.zone_description)
st.warning("Reference geometry is not an independently verified legal boundary. Current occupancy and vacancy are not verified.")
with st.expander("Source and environmental evidence",expanded=True):
    cols=["zone_division","environment_cluster","geometry_status","geometry_method",
          "geometry_source_evidence","official_capacity",
          "mapped_landuse_coverage_ratio_500m","commercial_poi_count_250m",
          "market_poi_count_500m","food_poi_count_250m","distance_to_major_road_m",
          "distance_to_bus_access_m","bus_count_500m","healthcare_count_500m",
          "education_count_500m","toilet_count_500m","parking_count_500m"]
    st.dataframe(pd.DataFrame({"Field":cols,"Value":[r.get(c,"") for c in cols]}),
                 hide_index=True,use_container_width=True)
st.caption("The MCDA score and historical business compatibility are intentionally hidden to reduce anchoring. Assess suitability based on your independent expertise and available evidence.")
with st.form("review",clear_on_submit=True):
    relevance=st.selectbox("Suitability judgment",list(SCALE),format_func=lambda x:SCALE[x],index=None,
                           placeholder="Choose a rating")
    recommendation=st.selectbox("Evidence decision",
        ["Sufficient evidence to rate","Insufficient evidence / abstain","Requires site verification"],index=None)
    confidence=st.selectbox("Confidence",["Low","Medium","High"],index=None)
    reason=st.text_area("Reason and evidence used",placeholder="Explain the business–location fit, concerns, and any source limitations.")
    acknowledged=st.checkbox("I am providing an independent research judgment, not a permit or verified business outcome.")
    submitted=st.form_submit_button("Save judgment",type="primary")
    if submitted:
        if recommendation is None or confidence is None or not reason.strip() or not acknowledged:
            st.error("Complete the decision, confidence, reason, and acknowledgment.")
        elif recommendation=="Sufficient evidence to rate" and relevance is None:
            st.error("Select a relevance rating.")
        elif recommendation!="Sufficient evidence to rate" and relevance is not None:
            st.error("Leave relevance blank when abstaining or requesting site verification.")
        else:
            record={"pair_id":r.pair_id,"vendor_profile_id":r.vendor_profile_id,
                "business_category":r.business_category,"preferred_division":r.preferred_division,
                "zone_id":r.zone_id,"reviewer_id":reviewer.strip(),
                "reviewed_at_utc":datetime.now(timezone.utc).isoformat(),
                "relevance":relevance if relevance is not None else "",
                "recommendation":recommendation,"confidence":confidence,"reason":reason.strip(),
                "evidence_version":r.evidence_version}
            try:
                write_label(record)
                st.success("Judgment saved. Select the next pair.")
            except ValueError as exc:st.error(str(exc))
