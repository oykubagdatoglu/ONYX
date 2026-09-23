import json
import os

import streamlit as st

import llm
from rules import SHIFT, WORKERS, pick_best, rank_candidates

st.set_page_config(page_title="Onyx – shift fill agent", page_icon="🟣", layout="wide")

OFFERS_PER_ROUND = 3
MODE_LABELS = {
    "cascade": "Cascade: Qwen3-30B → gpt-oss-120b only if unsure",
    "small": "Qwen3-30B-A3B only",
    "big": "gpt-oss-120b only",
}

ss = st.session_state
ss.setdefault("cancelled", False)
ss.setdefault("offers", [])        # list of {name, rank, reply, result, parsed}
ss.setdefault("next_rank", 0)
ss.setdefault("confirmed", None)
ss.setdefault("spent", 0.0)

with st.sidebar:
    st.markdown("### ⚙️ Model")
    mode = st.radio("Reply understanding", list(MODE_LABELS), format_func=MODE_LABELS.get, index=2)
    st.caption("All models are open-weight, served on Nebius Token Factory (EU).")
    st.metric("Model cost this session", f"${ss.spent:.5f}")
    if not llm.get_api_key():
        st.error("NEBIUS_API_KEY missing (Streamlit secrets or env var).")
    if st.button("🔄 Reset demo"):
        for k in ["cancelled", "offers", "next_rank", "confirmed", "spent"]:
            del ss[k]
        st.rerun()

st.title("🟣 Onyx")
st.caption("Fills last-minute shift gaps from your own trained team — within the Dutch flex-law hour bands.")

tab_demo, tab_proof, tab_design = st.tabs(["Live shift fill", "Proof: model benchmark", "How it works & responsible design"])

eligible, excluded = rank_candidates(WORKERS, SHIFT)

with tab_proof:
    st.subheader("Same 60 messy multilingual replies, five setups")
    path = os.path.join(os.path.dirname(__file__), "benchmark", "results.json")
    if os.path.exists(path):
        with open(path) as f:
            res = json.load(f)
        rows = []
        for r in res["summary"]:
            rows.append({
                "Setup": r["setup"],
                "Accuracy": f"{r['accuracy']*100:.1f}%",
                "Status accuracy": f"{r['status_accuracy']*100:.1f}%",
                "Median latency": f"{r['median_latency_s']:.2f}s",
                "Cost / 1,000 replies": f"${r['cost_per_1000']:.4f}",
                "Escalated to 120b": f"{r['escalation_rate']*100:.0f}%" if r.get("escalation_rate") is not None else "—",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption(f"Test set: {res['n']} replies in NL/EN/TR/PL/ES, labelled by hand. "
                   "Accuracy = status and (for partial) both times exactly right.")
        errs = res.get("cascade_errors", [])
        if errs:
            with st.expander(f"Where the cascade was wrong ({len(errs)})"):
                st.json(errs)
    else:
        st.info("Run `python benchmark/run_benchmark.py` and commit benchmark/results.json.")

with tab_design:
    st.markdown("""
**Pipeline**
1. Rule check (plain code, no AI): trained for location · no overlap · stays inside contract hour band · ranked by hours already guaranteed, then fewest recent offers.
2. Offers go out in each worker's own chat language.
3. **gpt-oss-120b** turns each free-text reply into structured availability (status + time window + confidence).
   We also built and measured a cascade (Qwen3-30B-A3B first, 120b only if unsure). The benchmark showed the small model is
   confidently wrong on a few replies, so its confidence is not a safe routing signal — we made gpt-oss-120b the default.
4. Manager approves. Nothing is booked automatically.

**Responsible design**
- Human in the loop: the manager confirms every booking; unclear replies are flagged, never guessed.
- Fairness: offers rotate by hours owed and recent offers; declining has no penalty and is not scored.
- Legal guardrails: hour-band limits are enforced by rules, not by the model.
- Privacy: only first name, availability and hours are processed; open models on Nebius in the EU; demo data is fictional.
""")

with tab_demo:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader(f"{SHIFT['location']} · {SHIFT['day']} {SHIFT['start']}–{SHIFT['end']}")
    with c2:
        if not ss.cancelled:
            if st.button(f"❌ {SHIFT['cancelled_by']} cancels this shift", type="primary", use_container_width=True):
                ss.cancelled = True
                st.rerun()
        elif ss.confirmed:
            st.success(f"✅ Filled by {ss.confirmed}")
        else:
            st.warning("Shift open — agent working")

    if not ss.cancelled:
        st.info("Shift is covered. Simulate a cancellation to start the agent.")
        st.stop()

    # Step 1: rule check
    st.markdown("#### 1 · Who is allowed to take it?")
    left, right = st.columns(2)
    with left:
        st.markdown("**Eligible (ranked)**")
        for i, w in enumerate(eligible, 1):
            st.markdown(f"{i}. **{w['name']}** ({w['lang']}) — {w['hours_this_week']}h/{w['contract_min']}–{w['contract_max']}h · "
                        f"{w['offers_14d']} offers in 14d  \n<span style='color:gray'>{w['reason']}</span>", unsafe_allow_html=True)
    with right:
        st.markdown("**Excluded automatically**")
        for w in excluded:
            st.markdown(f"🚫 **{w['name']}** — {w['reason']}")

    # Step 2: offers
    st.markdown("#### 2 · Offers sent in each worker's own chat")
    if not ss.offers:
        if st.button(f"📨 Send offers to top {OFFERS_PER_ROUND}"):
            for w in eligible[:OFFERS_PER_ROUND]:
                ss.offers.append({"name": w["name"], "rank": ss.next_rank, "reply": w["demo_reply"], "result": None, "parsed": None})
                ss.next_rank += 1
            st.rerun()
    else:
        cols = st.columns(len(ss.offers))
        for col, offer in zip(cols, ss.offers):
            with col:
                with st.container(border=True):
                    st.markdown(f"📱 **{offer['name']}**")
                    st.caption(f"Offer: {SHIFT['day']} {SHIFT['start']}–{SHIFT['end']} at {SHIFT['location']}. Can you?")
                    if offer["result"] is None:
                        offer["reply"] = st.text_input("Reply", offer["reply"], key=f"reply_{offer['name']}")
                        if st.button("Send reply", key=f"send_{offer['name']}"):
                            try:
                                with st.spinner("Understanding reply…"):
                                    r = llm.parse_reply(offer["reply"], SHIFT["start"], SHIFT["end"], mode=mode)
                                offer["result"], offer["parsed"] = r, r["parsed"]
                                ss.spent += r["cost_usd"]
                            except Exception as e:
                                st.error(f"Model call failed: {e}")
                            st.rerun()
                    else:
                        st.markdown(f"💬 _“{offer['reply']}”_")
                        p, r = offer["parsed"], offer["result"]
                        if p:
                            icon = {"yes": "🟢", "no": "🔴", "partial": "🟡"}[p["status"]]
                            times = f" {p['from']}–{p['until']}" if p["status"] == "partial" else ""
                            st.markdown(f"{icon} **{p['status'].upper()}{times}** · {p.get('note', '')}")
                        else:
                            st.markdown("⚪ Could not understand — flagged for the manager")
                        path = " → ".join(m.split("/")[-1] for m in r["path"])
                        st.caption(f"{path} · {r['latency_s']:.2f}s · ${r['cost_usd']:.6f}")
                        with st.expander("Structured output"):
                            st.json(p or {"raw": r["raw"]})

        answered = [o for o in ss.offers if o["result"] is not None]
        if len(answered) == len(ss.offers):
            best = pick_best(ss.offers)
            # Step 3: manager decides
            st.markdown("#### 3 · Manager approves (the agent never books anyone on its own)")
            if best and not ss.confirmed:
                p = best["parsed"]
                label = f"{best['name']} — full shift" if p["status"] == "yes" else f"{best['name']} — {p['from']}–{p['until']} (partial)"
                st.info(f"Suggested: **{label}**")
                if st.button(f"✅ Approve {best['name']}", type="primary"):
                    ss.confirmed = best["name"]
                    st.rerun()
            elif not best and not ss.confirmed:
                remaining = eligible[ss.next_rank:]
                if remaining:
                    if st.button(f"➡️ Nobody available — offer to {remaining[0]['name']}"):
                        w = remaining[0]
                        ss.offers.append({"name": w["name"], "rank": ss.next_rank, "reply": w["demo_reply"], "result": None, "parsed": None})
                        ss.next_rank += 1
                        st.rerun()
                else:
                    st.error("No eligible worker left — escalate to agency.")
            if ss.confirmed:
                st.success(f"✅ {ss.confirmed} confirmed. Others get a polite 'filled, thanks' message. Total model cost: ${ss.spent:.5f}")
