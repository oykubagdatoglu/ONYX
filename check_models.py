"""Quick check: can we reach Nebius, and do our two model IDs exist?"""
import llm

ids = [m.id for m in llm.client().models.list().data]
for want in (llm.SMALL_MODEL, llm.BIG_MODEL):
    print(("OK      " if want in ids else "MISSING ") + want)
    if want not in ids:
        close = [i for i in ids if want.split("/")[-1].lower()[:10] in i.lower()]
        print("   similar:", close or "none")
r = llm.parse_reply("kan vanaf half 7")
print("Test reply ->", r["parsed"], "| via", r["path"], f"| {r['latency_s']:.2f}s")
