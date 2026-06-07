# Remaining Work to 80% / 90% / 95% Core Parity

**Audit date:** 2026-06-07
**Head commit:** see `git log -1 --format=%H` on the head of the next push (post-File-Diff-Batch-2)
**Current weighted core OpenCode-style parity:** **82.40%** (post-File-Diff-Batch-2; was 79.60% before)
**Remaining core work:** **17.60%** of weighted core
**Future expansion readiness:** **4.5%** (GitHub bot 0%, browser/mobile 0%, workflow builder 0% — excluded from core score)

Source: `current-parity-scorecard.json`, `103-current-progress-audit.md`.

---

## 1. What is left to reach **80%** (gap = 0.80%)

The headline number is 79.60%, so a true 80% is less than 0.5 weighted points away. The cheapest, lowest-risk, audit-cleanest way to cross 80% is one of the following single-batches:

| Option | What it changes | Weighted delta | Risk | Time |
| --- | --- | --- | --- | --- |
| **A. Fix the 5 small low-weight gaps** (CI/release/Windows 78→85, Artifact 66→70, Project config 75→80) | tiny fixes in 3 categories | +0.50 to +0.60 | very low | 0.5 day |
| **B. Add Memory/compaction live Qdrant smoke only** (70→75) | one compose override + one smoke | +0.30 | low (infra only) | 0.5 day |
| **C. Add 1 small Web UI component test (Playwright smoke)** (70→72) | one Playwright test for the Dashboard render path | +0.12 | medium (first test = setup cost) | 1 day |

**Recommended:** Option A + B together. Total +0.80 to +0.90 weighted points, lands at **80.0%** with almost zero risk and no schema or contract changes.

### Concrete subtasks for "80%"

1. CI/release/Windows: 88 → 90 (+0.08) — the polling fix is **DONE** in the verifier-hardening batch; only Windows ARM64 and artifact signing remain.
   - Add `Windows-latest-arm64` runner matrix entry.
2. Project config: 75 → 80 (+0.20)
   - Create the missing `docs/windows-first-development.md` referenced by the matrix.
   - Add JSON schema validation with user-friendly error messages.
3. Artifact/report/export: 66 → 70 (+0.16)
   - Add HTML export alongside Markdown/JSON.
4. Memory/compaction: 70 → 75 (+0.30)
   - Add `docker-compose.qdrant.yml` override for the dev stack.
   - Add `scripts/smoke-memory-qdrant.ps1` that exercises the live path.

**Total expected weighted lift:** 0.08 + 0.20 + 0.16 + 0.30 = **+0.74 weighted points** → 80.34%.

---

## 2. What is left to reach **90%** (gap = 10.40%)

To go from 79.60% to 90% we need roughly **+10.4 weighted points**. The realistic path is one medium batch plus a few small ones. The order matters because File Diff Batch 2 has the highest ROI.

| Batch | Categories touched | Weighted delta | Risk | Time |
| --- | --- | --- | --- | --- |
| **1. File Diff Batch 2** (approval gate + 409 contract + batch revert + git/VCS fallback + round-trip smoke) | File diff 88→94 | **+0.60** | medium (contract change) | 2 days |
| **2. Web UI test infrastructure** (Playwright e2e + Vitest unit + axe a11y + bundle budget + wire sessionSocket) | Web UI 70→85 | **+0.90** | medium | 3 days |
| **3. Memory/compaction real backend** (live Qdrant + active embeddings + compaction load-test) | Memory 70→88 | **+1.08** | medium-high (infra) | 2 days |
| **4. MCP HTTP/SSE + plugin sandbox (Windows Job Object)** | MCP/plugin 72→84 | **+0.72** | medium-high | 3 days |
| **5. Agent modes polish** (plan→build approval surface + persistent memory + telemetry) | Agent modes 72→84 | **+0.96** | medium | 2 days |
| **6. CLI/TUI polish** (slash auto-complete + theme switcher) | CLI/TUI 80→85 | **+0.50** | low | 1 day |
| **7. Project config hot-reload + per-workspace overlay** | Project config 75→88 | **+0.52** | low | 1 day |
| **8. CI/release/Windows harden** (polling fix DONE; ARM64 + signing remain) | CI 88→90 | **+0.08** | low | 0.5 day |
| **9. Artifact/report/export full** (HTML/PDF + preview component) | Artifact 66→82 | **+0.64** | medium | 2 days |
| **10. Model/provider manager UI + fallback chain** | Model/provider 62→82 | **+0.80** | medium | 2 days |
| **11. Tool system rate limit + semantic truncation** | Tool system 88→93 | **+0.50** | medium | 1.5 days |

**Total: ~+7.7 weighted points** under realistic upper bounds; +9.5 under optimistic. Reaching 90% requires **at least batches 1–7** to land cleanly (sum ≈ +5.8) and one of 9/10/11. The most cost-effective path to 90% is **batches 1, 2, 3, 4, 5** which sum to **+4.26** plus the 80%-target work in section 1 (+0.94) = **+5.2**. To get to 90% we also need the 6+ point gain from 8/9/10/11, which is doable in 2 weeks focused work.

### Subtasks in execution order for "90%"

1. Section 1 work (cheap, +0.94) — 0.5 day
2. File Diff Batch 2 (+0.60) — 2 days
3. Agent modes polish (+0.96) — 2 days
4. Project config hot-reload (+0.52) — 1 day
5. Memory/compaction real backend (+1.08) — 2 days
6. MCP HTTP/SSE + plugin sandbox (+0.72) — 3 days
7. CLI/TUI polish (+0.50) — 1 day
8. CI/release harden (+0.48) — 1 day
9. Web UI test infrastructure (+0.90) — 3 days (run in parallel with 5–8)
10. Model/provider manager UI (+0.80) — 2 days

**Cumulative weighted:** 0.94 + 0.60 + 0.96 + 0.52 + 1.08 + 0.72 + 0.50 + 0.48 + 0.90 + 0.80 = **+7.5** → **86.7%**.
We need another +3.3 weighted points to land at 90%. That comes from:
- File diff Batch 3 (codemod-aware diffs, 94→98): +0.40
- Tool system rate limit + semantic truncation: +0.50
- Artifact full HTML/PDF + preview: +0.64
- One more category polish round: ~+1.5 to +2.0

**Realistic 90% ETA:** ~3–4 weeks of focused, single-developer work, with Web UI test infrastructure and Memory live backend running in parallel with sequential backend batches.

---

## 3. What is left to reach **95%** (gap = 15.40%)

To reach 95% we need **+15.8 weighted points**. This requires almost every category to reach its "complete + smoke + CI" tier, plus the gap-bridging work below. The likely "95% shape":

- All categories at ≥ 85.
- File diff, Tool system, Permission+human, LSP/codeintel, Core runtime at ≥ 90.
- Web UI with at least 30 e2e tests and a11y passes.
- Memory on a real backend with a load-test smoke.
- MCP HTTP/SSE + plugin sandbox in CI.
- Project config hot-reload + per-workspace overlay.
- CI/release/Windows at 90+ (polling bug is RESOLVED; only ARM64 and signing remain at that point).

This is roughly 2× the 90% work, plus deeper investment in Web UI and Memory. **Realistic 95% ETA:** ~6–8 weeks focused, single-developer.

The 5% above 95% is mostly the "exact OpenCode UX" surface (theme engine, advanced slash-command DSL, plugin marketplace, OAuth flows) which is not worth the ROI before product testing.

---

## 4. What is **probably not worth doing** before product testing

These items have low ROI relative to the effort, and the product surface is not stable enough to justify the investment:

- **MCP OAuth PKCE flow.** No real remote MCP server is in use yet. Add only when a customer asks for it.
- **Workflow builder.** The existing CLI commands + agent modes cover the same surface; a builder is a separate UX project.
- **Theme engine (CLI + Web UI).** Cosmetic; one theme is fine until user feedback demands more.
- **Provider fallback chain + per-session cost budget.** Useful, but the failure modes (rate limit, model down) are not common enough in early testing to justify the work.
- **Artifact HTML/PDF export + chart rendering.** Nice for share-out, but the Markdown/JSON export already satisfies the audit-trail use case.
- **Windows ARM64 in the CI matrix.** Worth doing for parity, but defer until a Windows-ARM user reports.
- **Release artifact signing.** Defer to first public release.

Together these are roughly **+1.0 to +1.5 weighted points** of work that is more cosmetic than functional.

---

## 5. What **must wait** until after core is stable (≥ 90%)

These are excluded from the core 14-category score for a reason: they are large, separate deployment artifacts that distract from the local-first product.

- **GitHub bot / PR review** (18% weight in a hypothetical "full" score, 0% today). Opencode-style GitHub bot is a separate deployable; it needs auth, secrets, CI/CD, and a security review. Do **not** start until core is ≥ 90%.
- **Browser/mobile automation** (0% today). Not part of the OpenCode-style core feature set. Different team / different stack.
- **Workflow builder** (0% today). Different UX paradigm; needs design exploration.
- **Cloud providers beyond Ollama/OpenAI/Anthropic** (Bedrock, Vertex, etc.). Only add when a paying customer asks.
- **Per-workspace project config overlay with multi-tenant sync.** Needs a real product surface to motivate it.
- **Plugin marketplace / third-party plugin registry.** Different security model; needs the plugin sandbox to be solid first.
- **Session replay / cross-process event bus.** Architectural; needs the core event bus to be load-tested first.

---

## Summary

| Target | Gap (weighted points) | Realistic ETA (focused, single dev) | Required work |
| --- | --- | --- | --- |
| **80%** | +0.40 | **0.5 day** | CI ARM64 runner + missing docs file + HTML export + Qdrant smoke (polling fix already shipped) |
| **90%** | +10.40 | **3–4 weeks** | 80% work + File Diff Batch 2 + Web UI tests + Memory live + MCP HTTP/SSE + agent polish + CLI polish + project config hot-reload + provider manager |
| **95%** | +15.40 | **6–8 weeks** | 90% work + codemod-aware diffs + tool rate limit/semantic truncation + artifact HTML/PDF/preview + Web UI a11y + a11y + accessibility polish + theme engine |
| **100%** | +20.40 | months, possibly never | above + OAuth PKCE + plugin marketplace + GitHub bot + browser automation + per-workspace config overlay |

**Bottom line:** the product is **about one focused day away from 80%**, **one focused month away from 90%**, and **two focused months away from 95%**. The last 5% is mostly cosmetic OpenCode-UX surface and is not worth pursuing before user testing.
