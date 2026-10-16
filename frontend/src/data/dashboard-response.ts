// Generated from backend public serialization schemas. Do not edit by hand.
// Regenerate: python -m app.generate_public_contract (from backend/).
// Check: add --check. Runtime input still requires validation.

export type ApiErrorResponse = {
  readonly "error": ErrorBody;
};

export type CatalogIndicator = {
  readonly "indicator_id": string;
  readonly "series": ReadonlyArray<CatalogSeries>;
  readonly "summary_requirements": ReadonlyArray<string>;
};

export type CatalogResponseV1 = {
  readonly "data": ReadonlyArray<CatalogIndicator>;
  readonly "meta": ResponseMeta;
};

export type CatalogSeries = {
  readonly "series_id": string;
  readonly "name": string;
  readonly "definition_id": string | null;
  readonly "definition": string;
  readonly "unit": "percent_yoy" | "percent_of_gdp" | "percent" | "percentage_points" | "inr_crore" | "usd_billion" | "index_points" | null;
  readonly "frequency": string;
  readonly "basis": "fiscal" | "calendar" | null;
  readonly "status": "selected" | "derived" | "blocked";
  readonly "reason_code": string | null;
  readonly "available_periods": ReadonlyArray<ResponsePeriod>;
  readonly "source_id": string;
  readonly "limitations": ReadonlyArray<string>;
};

export type DashboardData = {
  readonly "panels": Readonly<Record<string, ResponsePanel>>;
  readonly "ticker": ResponseTicker;
};

export type DashboardResponseV1 = {
  readonly "data": DashboardData;
  readonly "meta": ResponseMeta;
};

export type ErrorBody = {
  readonly "code": string;
  readonly "message": string;
  readonly "details"?: ReadonlyArray<ErrorDetail>;
};

export type ErrorDetail = {
  readonly "location": ReadonlyArray<string | number>;
  readonly "message": string;
};

export type HistoryData = {
  readonly "indicator_id": string;
  readonly "series_id": string;
  readonly "selected_period": ResponsePeriod | null;
  readonly "series": ResponseSeries;
  readonly "superseded": ReadonlyArray<NormalizedObservation>;
};

export type HistoryResponseV1 = {
  readonly "data": HistoryData;
  readonly "meta": ResponseMeta;
};

export type LoginRequest = {
  readonly "username": string;
  readonly "password": string;
};

export type LoginResponse = {
  readonly "access_token": string;
  readonly "token_type"?: "bearer";
  readonly "expires_in": number;
  readonly "expires_at": string;
  readonly "user": PublicIdentity;
};

export type NormalizedObservation = {
  readonly "indicator_id": string;
  readonly "series_id": string;
  readonly "definition_id": string;
  readonly "value": string | null;
  readonly "unit": "percent_yoy" | "percent_of_gdp" | "percent" | "inr_crore" | "usd_billion" | "index_points";
  readonly "observation_period": ObservationPeriod;
  readonly "as_of": string;
  readonly "as_of_precision": "year" | "month";
  readonly "as_of_kind"?: "period_end";
  readonly "published_at": string | null;
  readonly "publication_precision"?: "minute" | null;
  readonly "publication_timezone": string | null;
  readonly "retrieved_at": string;
  readonly "sources": ReadonlyArray<SourceReference>;
  readonly "quality_status": "valid" | "missing";
  readonly "reason_code": string | null;
  readonly "revision_kind": "published" | "provisional" | "first_revised" | "final" | "provisional_actual";
  readonly "vintage_id": string;
  readonly "parser_version": string;
  readonly "source_unit": string;
  readonly "normalization_id"?: string;
  readonly "dataset_updated_at"?: string | null;
  readonly "transform_id"?: "exports_minus_imports_v1" | null;
  readonly "inputs"?: ReadonlyArray<NormalizedObservation>;
};

export type ObservationPeriod = {
  readonly "id": string;
  readonly "label": string;
  readonly "basis": "calendar" | "fiscal";
  readonly "frequency": "annual" | "monthly" | "monthly_cumulative";
  readonly "start": string;
  readonly "end": string;
};

export type PanelResponseV1 = {
  readonly "data": ResponsePanel;
  readonly "meta": ResponseMeta;
};

export type PublicIdentity = {
  readonly "user_id": string;
  readonly "username": string;
};

export type ResponseChart = {
  readonly "periods": ReadonlyArray<ResponsePeriod>;
  readonly "domain": readonly [string, string];
  readonly "ticks": ReadonlyArray<string>;
  readonly "unit": "percent_yoy" | "percent_of_gdp" | "percent" | "percentage_points" | "inr_crore" | "usd_billion" | "index_points";
  readonly "precision"?: number;
  readonly "annotation_precision"?: number;
};

export type ResponseComparison = {
  readonly "value": string;
  readonly "unit": "percentage_points" | "percent";
  readonly "precision": number;
  readonly "reference_label": string;
  readonly "kind": "previous_period" | "previous_year";
  readonly "reference_series_id": string;
  readonly "reference_period_id": string;
  readonly "verified"?: true;
  readonly "transform_id": string;
  readonly "exact_numerator": string;
  readonly "exact_denominator": string;
};

export type ResponseHistory = {
  readonly "status": "fresh" | "stale" | "unavailable" | "empty" | "error";
  readonly "points": ReadonlyArray<ResponseObservation>;
  readonly "truncated": boolean;
};

export type ResponseMeta = {
  readonly "api_version"?: "v1";
  readonly "generated_at": string;
  readonly "version": string;
  readonly "partial": boolean;
  readonly "data_version": string;
  readonly "poll_interval_seconds"?: 60;
};

export type ResponseObservation = {
  readonly "value": string | null;
  readonly "unit": "percent_yoy" | "percent_of_gdp" | "percent" | "percentage_points" | "inr_crore" | "usd_billion" | "index_points";
  readonly "definition_id": string;
  readonly "observation_period": ResponsePeriod | null;
  readonly "as_of": string | null;
  readonly "as_of_precision": "year" | "month" | null;
  readonly "as_of_kind": "period_end" | null;
  readonly "sources": ReadonlyArray<SourceReference>;
  readonly "status": "fresh" | "stale" | "unavailable" | "empty" | "error";
  readonly "reason_code": string | null;
  readonly "retention_allowed": boolean;
  readonly "published_at"?: string | null;
  readonly "retrieved_at"?: string | null;
  readonly "dataset_updated_at"?: string | null;
  readonly "revision_kind"?: string | null;
  readonly "vintage_id"?: string | null;
  readonly "parser_version"?: string | null;
  readonly "normalization_id"?: string | null;
  readonly "transform_id"?: string | null;
  readonly "inputs"?: ReadonlyArray<NormalizedObservation>;
  readonly "last_attempt_at"?: string | null;
  readonly "last_checked_at"?: string | null;
  readonly "last_success_at"?: string | null;
  readonly "last_changed_at"?: string | null;
  readonly "last_failure_at"?: string | null;
  readonly "publication_deadline"?: string | null;
  readonly "check_deadline"?: string | null;
  readonly "freshness_policy_version"?: string | null;
  readonly "failure_state_persisted"?: boolean | null;
};

export type ResponsePanel = {
  readonly "indicator_id": string;
  readonly "series": Readonly<Record<string, ResponseSeries>>;
  readonly "summaries": ReadonlyArray<ResponseSummary>;
  readonly "period_label": string | null;
  readonly "chart": ResponseChart | null;
};

export type ResponsePeriod = {
  readonly "id": string;
  readonly "label": string;
  readonly "basis": "fiscal" | "calendar";
  readonly "frequency": "annual" | "monthly" | "monthly_cumulative";
  readonly "start": string;
  readonly "end": string;
};

export type ResponseQuote = {
  readonly "value": string | null;
  readonly "unit"?: "index_points";
  readonly "definition_id": string;
  readonly "observation_period": ResponsePeriod | null;
  readonly "as_of": string | null;
  readonly "as_of_precision": "year" | "month" | null;
  readonly "as_of_kind": "period_end" | null;
  readonly "sources": ReadonlyArray<SourceReference>;
  readonly "status": "fresh" | "stale" | "unavailable" | "empty" | "error";
  readonly "reason_code": string | null;
  readonly "retention_allowed": boolean;
  readonly "published_at"?: string | null;
  readonly "retrieved_at"?: string | null;
  readonly "dataset_updated_at"?: string | null;
  readonly "revision_kind"?: string | null;
  readonly "vintage_id"?: string | null;
  readonly "parser_version"?: string | null;
  readonly "normalization_id"?: string | null;
  readonly "transform_id"?: string | null;
  readonly "inputs"?: ReadonlyArray<NormalizedObservation>;
  readonly "last_attempt_at"?: string | null;
  readonly "last_checked_at"?: string | null;
  readonly "last_success_at"?: string | null;
  readonly "last_changed_at"?: string | null;
  readonly "last_failure_at"?: string | null;
  readonly "publication_deadline"?: string | null;
  readonly "check_deadline"?: string | null;
  readonly "freshness_policy_version"?: string | null;
  readonly "failure_state_persisted"?: boolean | null;
  readonly "instrument_id": string;
  readonly "name": string;
  readonly "change"?: string | null;
  readonly "change_percent"?: string | null;
  readonly "comparison_label"?: string | null;
  readonly "precision"?: number;
  readonly "market_status"?: "unknown";
};

export type ResponseSeries = {
  readonly "name": string;
  readonly "precision"?: number;
  readonly "latest": ResponseObservation;
  readonly "comparison": ResponseComparison | null;
  readonly "comparison_reason_code": string | null;
  readonly "history": ResponseHistory;
  readonly "policy"?: null;
};

export type ResponseSummary = {
  readonly "slot": number;
  readonly "requirement_id": string;
  readonly "definition_id": string | null;
  readonly "unit": "percent_yoy" | "percent_of_gdp" | "percent" | "percentage_points" | "inr_crore" | "usd_billion" | "index_points" | null;
  readonly "observation": ResponseObservation | null;
  readonly "comparison": ResponseComparison | null;
  readonly "comparison_reason_code": string | null;
  readonly "reason_code": string | null;
};

export type ResponseTicker = {
  readonly "status"?: "unavailable";
  readonly "cadence"?: "unknown";
  readonly "cadence_label"?: null;
  readonly "items": ReadonlyArray<ResponseQuote>;
};

export type SourceReference = {
  readonly "source_id": string;
  readonly "name": string;
  readonly "url": string;
  readonly "is_nse": boolean;
};

export type TickerResponseV1 = {
  readonly "data": ResponseTicker;
  readonly "meta": ResponseMeta;
};
