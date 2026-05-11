"use client";

import { useState, useRef } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PublisherResult {
  publisher_id: string;
  name: string;
  category: string;
  subcategories: string[];
  fit_score: number;
  fit_reasoning: string;
  retrieval_source: string;
  rrf_score: number;
  aov_usd: number;
  monthly_impressions: number;
  income_tier: string;
  min_age: number;
  max_age: number;
  top_geos: string[];
  notes: string;
}

interface ExcludedPublisher {
  publisher_id: string;
  name: string;
  exclusion_reason: string;
}

interface PersonaMeta {
  age_range: string | null;
  gender_skew: string | null;
  description: string | null;
  typical_aov_usd: number | null;
  price_sensitivity: string | null;
  messaging_preferences: string[] | null;
  category_affinities: string[] | null;
  disinterested_in: string[] | null;
}

interface CreativeVariant {
  persona_name: string;
  persona_reasoning: string;
  headline: string;
  body_copy: string;
  persona_meta: PersonaMeta;
}

interface PublisherAllocation {
  publisher_id: string;
  publisher_name: string;
  budget_pct: number;
  monthly_impressions: number;
  fit_score: number;
  allocation_reasoning: string;
}

interface CampaignConfig {
  targeting: {
    categories: string[];
    income_tiers: string[];
    age_range: { min: number; max: number };
    geos: string[];
    gender_skew: string | null;
  };
  publisher_allocations: PublisherAllocation[];
  bid_strategy: string;
  bid_strategy_reasoning: string;
  flight_duration_days: number;
  brand_safety_flags: string[];
}

interface AnalyzeResponse {
  brief: string;
  ranked_publishers: PublisherResult[];
  excluded_publishers: ExcludedPublisher[];
  creative_variants: CreativeVariant[];
  campaign_config: CampaignConfig;
}

// Intermediate pipeline event payloads
interface StageStatus {
  stage: "understand" | "retrieve" | "rerank" | "generate" | null;
  message: string;
}

interface UnderstandResult {
  hard_facets: { categories: string[]; income_tiers: string[]; geos: string[] };
  soft_facets: { aov_min_usd: number | null; aov_max_usd: number | null; gender_skew: string | null };
  age_range: { min: number; max: number };
  facet_confidence: Record<string, number>;
  fts_keywords: string;
  embedding_query: string;
  persona_embedding_query: string;
}

interface RetrieveCandidate {
  id: string;
  name: string;
  category: string;
  rrf_score: number;
  retrieval_source: string;
  income_tier: string;
  min_age: number;
  max_age: number;
  aov_usd: number;
  top_geos: string[];
}

interface RetrieveResult {
  candidate_count: number;
  candidates: RetrieveCandidate[];
}

interface RerankPreview {
  recommended_count: number;
  excluded_count: number;
  top_publishers: { publisher_id: string; name: string; fit_score: number; fit_reasoning: string }[];
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceBadge({ source }: { source: string }) {
  const styles: Record<string, string> = {
    facet:  "bg-blue-50 text-blue-700",
    hybrid: "bg-purple-50 text-purple-700",
    dense:  "bg-violet-50 text-violet-700",
    sparse: "bg-orange-50 text-orange-700",
  };
  const key = source.split("+")[0].trim().toLowerCase();
  const style = styles[key] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${style}`}>{source || "—"}</span>
  );
}

function RetrievalSection({ result }: { result: RetrieveResult }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? result.candidates : result.candidates.slice(0, 5);
  const maxScore = result.candidates[0]?.rrf_score ?? 1;

  return (
    <section>
      <h2 className="text-base font-semibold text-gray-900 mb-2">
        Candidate Retrieval
        <span className="ml-2 text-sm font-normal text-gray-400">
          {result.candidate_count} candidates
        </span>
      </h2>
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="divide-y divide-gray-100">
          {shown.map((c, i) => (
            <div key={c.id} className="px-4 py-3 flex items-center gap-4">
              <span className="text-xs font-mono text-gray-300 w-5 shrink-0">#{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-sm font-medium text-gray-900">{c.name}</span>
                  <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{c.category}</span>
                  <SourceBadge source={c.retrieval_source} />
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-400">
                  <span>Age {c.min_age}–{c.max_age}</span>
                  <span>{c.income_tier}</span>
                  <span>AOV ${c.aov_usd}</span>
                  <span>{c.top_geos.slice(0, 2).join(", ")}</span>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-400 rounded-full"
                    style={{ width: `${(c.rrf_score / maxScore) * 100}%` }}
                  />
                </div>
                <span className="text-xs font-mono text-gray-400 w-12 text-right">
                  {c.rrf_score.toFixed(4)}
                </span>
              </div>
            </div>
          ))}
        </div>
        {result.candidates.length > 5 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full text-xs text-gray-400 hover:text-gray-600 py-2 border-t border-gray-100 hover:bg-gray-50 transition-colors"
          >
            {expanded
              ? "Show less"
              : `Show ${result.candidates.length - 5} more candidates`}
          </button>
        )}
      </div>
    </section>
  );
}

function FitScoreBadge({ score }: { score: number }) {
  const color =
    score >= 8 ? "bg-green-100 text-green-800" :
    score >= 6 ? "bg-yellow-100 text-yellow-800" :
    "bg-red-100 text-red-800";
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${color}`}>
      {score}/10
    </span>
  );
}

function PublisherCard({ pub, rank }: { pub: PublisherResult; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-sm font-mono text-gray-400 mt-0.5 shrink-0">#{rank}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-gray-900">{pub.name}</span>
              <FitScoreBadge score={pub.fit_score} />
              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                {pub.category}
              </span>
            </div>
            <p className="text-sm text-gray-600 mt-1">{pub.fit_reasoning}</p>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-gray-400 hover:text-gray-600 shrink-0 mt-0.5"
        >
          {expanded ? "less" : "more"}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-gray-500">
          <span>AOV: <strong className="text-gray-700">${pub.aov_usd}</strong></span>
          <span>Income: <strong className="text-gray-700">{pub.income_tier}</strong></span>
          <span>Age: <strong className="text-gray-700">{pub.min_age}–{pub.max_age}</strong></span>
          <span>Reach: <strong className="text-gray-700">{(pub.monthly_impressions / 1_000_000).toFixed(1)}M/mo</strong></span>
          <span className="col-span-2">Geos: <strong className="text-gray-700">{pub.top_geos.join(", ")}</strong></span>
          <span className="col-span-2">Subcategories: <strong className="text-gray-700">{pub.subcategories.join(", ")}</strong></span>
          <span className="col-span-2 flex items-center gap-2">
            <span>Retrieved via</span>
            <SourceBadge source={pub.retrieval_source} />
            <span className="text-gray-300">·</span>
            <span>RRF score <strong className="text-gray-700 font-mono">{pub.rrf_score.toFixed(4)}</strong></span>
          </span>
          <span className="col-span-2 text-gray-400 italic">{pub.notes}</span>
        </div>
      )}
    </div>
  );
}

function CreativeCard({ variant }: { variant: CreativeVariant }) {
  const [expanded, setExpanded] = useState(false);
  const m = variant.persona_meta;
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Persona header — always visible */}
      <div className="bg-indigo-50 border-b border-indigo-100 px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0" />
          <span className="text-sm font-semibold text-indigo-800">{variant.persona_name}</span>
          <span className="text-xs font-medium text-indigo-400 uppercase tracking-wide ml-1">Persona</span>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-indigo-400 hover:text-indigo-600 shrink-0"
        >
          {expanded ? "less" : "more"}
        </button>
      </div>

      {/* Persona attributes — expanded */}
      {expanded && m && (
        <div className="bg-indigo-50 border-b border-indigo-100 px-4 pb-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-indigo-700">
          {m.age_range && (
            <span>Age: <strong>{m.age_range}</strong></span>
          )}
          {m.gender_skew && (
            <span>Gender: <strong className="capitalize">{m.gender_skew}</strong></span>
          )}
          {m.typical_aov_usd != null && (
            <span>Typical AOV: <strong>${m.typical_aov_usd}</strong></span>
          )}
          {m.price_sensitivity && (
            <span>Price sensitivity: <strong className="capitalize">{m.price_sensitivity}</strong></span>
          )}
          {m.description && (
            <span className="col-span-2 text-indigo-500 italic">{m.description}</span>
          )}
          {m.messaging_preferences && m.messaging_preferences.length > 0 && (
            <span className="col-span-2">
              Messaging: <strong>{m.messaging_preferences.join(", ")}</strong>
            </span>
          )}
          {m.category_affinities && m.category_affinities.length > 0 && (
            <span className="col-span-2">
              Category affinities: <strong>{m.category_affinities.join(", ")}</strong>
            </span>
          )}
          {m.disinterested_in && m.disinterested_in.length > 0 && (
            <span className="col-span-2">
              Disinterested in: <strong>{m.disinterested_in.join(", ")}</strong>
            </span>
          )}
        </div>
      )}

      {/* Campaign copy — always visible, clearly separate */}
      <div className="bg-white px-4 pt-4 pb-4 space-y-3">
        <div>
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Headline</span>
          <p className="text-base font-bold text-gray-900 leading-snug mt-0.5">{variant.headline}</p>
        </div>
        <div>
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Body copy</span>
          <p className="text-sm text-gray-600 leading-relaxed mt-0.5">{variant.body_copy}</p>
        </div>
        <div className="border-t border-gray-100 pt-2">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Why this persona</span>
          <p className="text-xs text-gray-400 italic mt-0.5">{variant.persona_reasoning}</p>
        </div>
      </div>
    </div>
  );
}

function CampaignConfigPanel({ config }: { config: CampaignConfig }) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Targeting</h3>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="text-gray-500">Categories</span>
          <span className="text-gray-900">{config.targeting.categories.join(", ") || "—"}</span>
          <span className="text-gray-500">Income tiers</span>
          <span className="text-gray-900">{config.targeting.income_tiers.join(", ") || "—"}</span>
          <span className="text-gray-500">Age range</span>
          <span className="text-gray-900">{config.targeting.age_range.min}–{config.targeting.age_range.max}</span>
          <span className="text-gray-500">Geos</span>
          <span className="text-gray-900">{config.targeting.geos.join(", ") || "—"}</span>
          {config.targeting.gender_skew && (
            <>
              <span className="text-gray-500">Gender skew</span>
              <span className="text-gray-900">{config.targeting.gender_skew}</span>
            </>
          )}
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Bid Strategy</h3>
        <div className="flex items-center gap-2 mb-1">
          <span className="font-semibold text-gray-900">
            {config.bid_strategy === "CPM" && "CPM — Cost per Thousand Impressions"}
            {config.bid_strategy === "CPC" && "CPC — Cost per Click"}
            {config.bid_strategy === "CPA" && "CPA — Cost per Acquisition"}
          </span>
          <span className="text-xs text-gray-500">· {config.flight_duration_days} day flight</span>
        </div>
        <p className="text-sm text-gray-600">{config.bid_strategy_reasoning}</p>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Budget Allocation</h3>
        <div className="space-y-2">
          {config.publisher_allocations.map((alloc) => (
            <div key={alloc.publisher_id} className="flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between text-sm mb-0.5">
                  <span className="font-medium text-gray-900 truncate">{alloc.publisher_name}</span>
                  <span className="text-gray-600 shrink-0 ml-2">{alloc.budget_pct}%</span>
                </div>
                <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${alloc.budget_pct}%` }}
                  />
                </div>
                {alloc.allocation_reasoning && (
                  <p className="text-xs text-gray-500 mt-1">{alloc.allocation_reasoning}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {config.brand_safety_flags.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Brand Safety</h3>
          <div className="flex flex-wrap gap-1">
            {config.brand_safety_flags.map((flag) => (
              <span key={flag} className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded-full">
                {flag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Elapsed timer display
// ---------------------------------------------------------------------------

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const EXAMPLE_BRIEFS = [
  "We sell premium dog food for senior dogs, targeting owners who care about joint health and longevity.",
  "We make non-toxic cookware for health-conscious families who cook from scratch.",
  "We're a DTC vitamin brand for women in their 30s focused on energy and hormone balance.",
  "We sell sustainable running shoes for urban professionals who care about comfort and the environment.",
];

export default function Home() {
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);

  // Intermediate stage state
  const [stageStatus, setStageStatus] = useState<StageStatus>({ stage: null, message: "" });
  const [understandResult, setUnderstandResult] = useState<UnderstandResult | null>(null);
  const [retrieveResult, setRetrieveResult] = useState<RetrieveResult | null>(null);
  const [rerankPreview, setRerankPreview] = useState<RerankPreview | null>(null);

  // Timer
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // EventSource ref for cleanup
  const eventSourceRef = useRef<EventSource | null>(null);

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const handleSubmit = async () => {
    if (!brief.trim()) return;

    // Reset
    setLoading(true);
    setResult(null);
    setError(null);
    setShowExcluded(false);
    setStageStatus({ stage: null, message: "" });
    setUnderstandResult(null);
    setRetrieveResult(null);
    setRerankPreview(null);
    setElapsed(0);
    stopTimer();

    // Close any existing stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    try {
      // Step 1: POST to enqueue the job
      const res = await fetch("http://localhost:8000/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start job.");
      }
      const { job_id } = await res.json();

      // Start timer
      timerRef.current = setInterval(() => setElapsed((prev) => prev + 1), 1000);

      // Step 2: Open SSE stream
      const source = new EventSource(`http://localhost:8000/api/jobs/${job_id}/stream`);
      eventSourceRef.current = source;

      // Guard against onerror firing after a terminal event already closed the stream
      let terminalReceived = false;

      const closeStream = () => {
        terminalReceived = true;
        source.close();
        eventSourceRef.current = null;
      };

      source.addEventListener("status", (e: MessageEvent) => {
        const data = JSON.parse(e.data);
        setStageStatus({ stage: data.stage, message: data.message });
      });

      source.addEventListener("understand", (e: MessageEvent) => {
        setUnderstandResult(JSON.parse(e.data));
      });

      source.addEventListener("retrieve", (e: MessageEvent) => {
        setRetrieveResult(JSON.parse(e.data));
      });

      source.addEventListener("rerank", (e: MessageEvent) => {
        setRerankPreview(JSON.parse(e.data));
      });

      source.addEventListener("complete", (e: MessageEvent) => {
        setResult(JSON.parse(e.data) as AnalyzeResponse);
        setLoading(false);
        setStageStatus({ stage: null, message: "" });
        stopTimer();
        closeStream();
      });

      source.addEventListener("error", (e: MessageEvent) => {
        // Server-sent named "error" event (pipeline failure)
        const data = JSON.parse(e.data);
        setError(data.message || "Pipeline failed.");
        setLoading(false);
        stopTimer();
        closeStream();
      });

      source.onerror = () => {
        // Network-level failure — ignore if a terminal event already handled the close
        if (terminalReceived) return;
        setError("Connection lost. Please try again.");
        setLoading(false);
        stopTimer();
        closeStream();
      };

    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setLoading(false);
      stopTimer();
    }
  };

  const showTimer = loading || result !== null || error !== null;

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="border-b border-gray-200 bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-3">
          <span className="font-bold text-gray-900 text-lg">Disco</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-500 text-sm">Ad Placement</span>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {/* Brief input */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Advertiser brief
          </label>
          <textarea
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            rows={3}
            placeholder="Describe your business in a sentence or two…"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
          <div className="flex items-center justify-between mt-3">
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_BRIEFS.map((b, i) => (
                <button
                  key={i}
                  onClick={() => setBrief(b)}
                  className="text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
                >
                  Example {i + 1}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-3">
              {showTimer && (
                <span className="text-xs tabular-nums text-gray-400">
                  {formatElapsed(elapsed)}
                </span>
              )}
              <button
                onClick={handleSubmit}
                disabled={loading || !brief.trim()}
                className="bg-indigo-600 text-white text-sm font-medium px-5 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? "Analyzing…" : "Analyze"}
              </button>
            </div>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {/* Stage progress */}
        {loading && stageStatus.message && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 flex items-center gap-3">
            <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
            <span className="text-sm text-blue-700">{stageStatus.message}</span>
          </div>
        )}

        {/* Stage 1 result: understand */}
        {understandResult && (
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-3">Brief Understanding</h2>
            <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3 text-sm">
              {understandResult.hard_facets.categories?.length > 0 && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Categories</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {understandResult.hard_facets.categories.map((c) => (
                      <span key={c} className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{c}</span>
                    ))}
                  </div>
                </div>
              )}
              {understandResult.hard_facets.income_tiers?.length > 0 && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Income tiers</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {understandResult.hard_facets.income_tiers.map((t) => (
                      <span key={t} className="bg-green-50 text-green-700 px-2 py-0.5 rounded-full text-xs">{t}</span>
                    ))}
                  </div>
                </div>
              )}
              {understandResult.hard_facets.geos?.length > 0 && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Geos</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {understandResult.hard_facets.geos.map((g) => (
                      <span key={g} className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full text-xs">{g}</span>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <span className="text-gray-400 text-xs w-24 shrink-0">Age range</span>
                <span className="text-gray-700 text-xs">{understandResult.age_range.min}–{understandResult.age_range.max}</span>
              </div>
              {understandResult.soft_facets?.gender_skew && (
                <div className="flex items-center gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0">Gender skew</span>
                  <span className="text-gray-700 text-xs capitalize">{understandResult.soft_facets.gender_skew}</span>
                </div>
              )}
              {(understandResult.soft_facets?.aov_min_usd || understandResult.soft_facets?.aov_max_usd) && (
                <div className="flex items-center gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0">AOV range</span>
                  <span className="text-gray-700 text-xs">
                    {understandResult.soft_facets.aov_min_usd != null ? `$${understandResult.soft_facets.aov_min_usd}` : "—"}
                    {" – "}
                    {understandResult.soft_facets.aov_max_usd != null ? `$${understandResult.soft_facets.aov_max_usd}` : "no cap"}
                  </span>
                </div>
              )}
              {understandResult.fts_keywords && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Keywords</span>
                  <span className="text-gray-500 text-xs italic">{understandResult.fts_keywords}</span>
                </div>
              )}
              {understandResult.facet_confidence && Object.keys(understandResult.facet_confidence).length > 0 && (
                <div className="flex items-start gap-3 pt-1 border-t border-gray-100">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-1.5">Confidence</span>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
                    {Object.entries(understandResult.facet_confidence).map(([dim, score]) => {
                      const color = score >= 0.7 ? "text-green-600" : score >= 0.4 ? "text-yellow-600" : "text-red-500";
                      return (
                        <span key={dim} className="text-xs text-gray-500">
                          {dim.replace(/_/g, " ")}: <strong className={color}>{Math.round(score * 100)}%</strong>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
              {understandResult.embedding_query && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Publisher query</span>
                  <p className="text-gray-500 text-xs italic leading-relaxed">{understandResult.embedding_query}</p>
                </div>
              )}
              {understandResult.persona_embedding_query && (
                <div className="flex items-start gap-3">
                  <span className="text-gray-400 text-xs w-24 shrink-0 pt-0.5">Persona query</span>
                  <p className="text-gray-500 text-xs italic leading-relaxed">{understandResult.persona_embedding_query}</p>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Stage 2 result: retrieve */}
        {retrieveResult && (
          <RetrievalSection result={retrieveResult} />
        )}

        {/* Stage 3 result: rerank preview (hidden once final result arrives) */}
        {rerankPreview && !result && (
          <section>
            <h2 className="text-base font-semibold text-gray-900 mb-2">
              Reranked Publishers
              <span className="ml-2 text-sm font-normal text-gray-400">
                {rerankPreview.recommended_count} recommended · {rerankPreview.excluded_count} excluded
              </span>
            </h2>
            <div className="space-y-2">
              {rerankPreview.top_publishers.map((pub) => (
                <div key={pub.publisher_id} className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900 text-sm">{pub.name}</span>
                    <FitScoreBadge score={pub.fit_score} />
                    <span className="text-xs text-gray-400">(preview)</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">{pub.fit_reasoning}</p>
                </div>
              ))}
              {rerankPreview.recommended_count > rerankPreview.top_publishers.length && (
                <p className="text-xs text-gray-400 pl-1">
                  +{rerankPreview.recommended_count - rerankPreview.top_publishers.length} more…
                </p>
              )}
            </div>
          </section>
        )}

        {/* Final result */}
        {result && (
          <div className="space-y-8">
            <section>
              <h2 className="text-base font-semibold text-gray-900 mb-3">
                Recommended Publishers
                <span className="ml-2 text-sm font-normal text-gray-400">
                  {result.ranked_publishers.length} matches
                </span>
              </h2>
              <div className="space-y-3">
                {result.ranked_publishers.map((pub, i) => (
                  <PublisherCard key={pub.publisher_id} pub={pub} rank={i + 1} />
                ))}
              </div>

              {result.excluded_publishers.length > 0 && (
                <div className="mt-4">
                  <button
                    onClick={() => setShowExcluded(!showExcluded)}
                    className="text-sm text-gray-400 hover:text-gray-600"
                  >
                    {showExcluded ? "Hide" : "Show"} {result.excluded_publishers.length} excluded publishers
                  </button>
                  {showExcluded && (
                    <div className="mt-3 space-y-2">
                      {result.excluded_publishers.map((pub) => (
                        <div
                          key={pub.publisher_id}
                          className="flex items-start gap-3 text-sm text-gray-500 border border-dashed border-gray-200 rounded-lg px-4 py-2"
                        >
                          <span className="font-medium text-gray-600 shrink-0">{pub.name}</span>
                          <span>{pub.exclusion_reason}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            <section>
              <h2 className="text-base font-semibold text-gray-900 mb-3">
                Ad Creative Variants
                <span className="ml-2 text-sm font-normal text-gray-400">by persona</span>
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {result.creative_variants.map((v, i) => (
                  <CreativeCard key={i} variant={v} />
                ))}
              </div>
            </section>

            <section>
              <h2 className="text-base font-semibold text-gray-900 mb-3">Campaign Config</h2>
              <div className="bg-white border border-gray-200 rounded-xl p-6">
                <CampaignConfigPanel config={result.campaign_config} />
              </div>
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
