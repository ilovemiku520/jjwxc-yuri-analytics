export interface CatalogFreshness {
  latest_observed_at: string | null;
  author_count: number;
  work_count: number;
  tag_count: number;
  metric_snapshot_count: number;
}

export interface CatalogTag {
  tag_name: string;
  tag_translation: string | null;
}

export interface CatalogWork {
  work_id: string;
  work_title: string;
  author_id: string;
  author_display_name: string;
  created_at: string;
  page_count: number;
  width: number | null;
  height: number | null;
  public_view_count: number | null;
  public_bookmark_count: number | null;
  public_like_count: number | null;
  public_tags: CatalogTag[];
}

export interface CatalogWorkPage {
  items: CatalogWork[];
  next_cursor: string | null;
}

export interface AuthorAggregate {
  author_id: string;
  author_display_name: string;
  work_count: number;
  total_public_view_count: number;
  total_public_bookmark_count: number;
  total_public_like_count: number;
}

export interface AuthorAggregatePage {
  items: AuthorAggregate[];
  next_cursor: string | null;
}

export type RankingMetric =
  | "likes"
  | "bookmarks"
  | "views"
  | "works"
  | "average_likes"
  | "average_bookmarks";

export interface AuthorRankingItem {
  author_id: string;
  author_display_name: string;
  work_count: number;
  metric_coverage_count: number;
  score: number;
  score_scale: 1 | 100;
}

export interface AuthorRankingPage {
  metric: RankingMetric;
  items: AuthorRankingItem[];
  next_cursor: string | null;
}

export interface AuthorDetail extends AuthorAggregate {
  first_seen_at: string;
  last_seen_at: string;
}

export interface AuthorMetricCoverage {
  public_view_count: number;
  public_bookmark_count: number;
  public_like_count: number;
}

export interface AuthorTagAffinity extends CatalogTag {
  work_count: number;
  work_share_basis_points: number;
}

export interface AuthorAnalyticsProfile {
  author_id: string;
  author_display_name: string;
  analyzed_work_count: number;
  first_work_created_at: string | null;
  latest_work_created_at: string | null;
  total_page_count: number;
  total_public_view_count: number | null;
  total_public_bookmark_count: number | null;
  total_public_like_count: number | null;
  public_bookmark_rate_basis_points: number | null;
  public_like_rate_basis_points: number | null;
  metric_coverage: AuthorMetricCoverage;
  top_public_tags: AuthorTagAffinity[];
}

export interface AuthorDailyMetricTrend {
  day: string;
  observed_work_count: number;
  public_view_coverage_count: number;
  public_bookmark_coverage_count: number;
  public_like_coverage_count: number;
  total_public_view_count: number | null;
  total_public_bookmark_count: number | null;
  total_public_like_count: number | null;
}

export interface AuthorMetricTrendResponse {
  author_id: string;
  date_from: string;
  date_to: string;
  items: AuthorDailyMetricTrend[];
}

export interface AuthorMetricCohortGrowth {
  complete_work_count: number;
  start_total: number | null;
  end_total: number | null;
  absolute_change: number | null;
  growth_basis_points: number | null;
}

export interface AuthorCohortGrowthResponse {
  author_id: string;
  date_from: string;
  date_to: string;
  start_observed_work_count: number;
  end_observed_work_count: number;
  matched_work_count: number;
  start_only_work_count: number;
  end_only_work_count: number;
  public_views: AuthorMetricCohortGrowth;
  public_bookmarks: AuthorMetricCohortGrowth;
  public_likes: AuthorMetricCohortGrowth;
}

export type AuthorQualityQuadrant = "core" | "boutique" | "ordinary" | "volume";

export interface AuthorQualityMapItem {
  author_id: string;
  author_display_name: string;
  work_count: number;
  bookmark_coverage_count: number;
  average_public_bookmark_count_x100: number;
  like_coverage_count: number;
  total_public_like_count: number | null;
  quadrant: AuthorQualityQuadrant;
}

export interface AuthorQualityMapResponse {
  sampled_author_count: number;
  sample_truncated: boolean;
  work_count_threshold_x100: number;
  average_bookmark_threshold_x100: number;
  items: AuthorQualityMapItem[];
}

export interface AuthorInfluenceWeights {
  bookmark: number;
  like: number;
  production: number;
}

export interface AuthorInfluenceRankingItem {
  author_id: string;
  author_display_name: string;
  work_count: number;
  complete_metric_work_count: number;
  average_public_bookmark_count_x100: number;
  average_public_like_count_x100: number;
  bookmark_component_basis_points: number;
  like_component_basis_points: number;
  production_component_basis_points: number;
  influence_score_basis_points: number;
}

export interface AuthorInfluenceRankingResponse {
  model_version: string;
  weights: AuthorInfluenceWeights;
  sampled_author_count: number;
  sample_truncated: boolean;
  items: AuthorInfluenceRankingItem[];
}

export interface TagAggregate extends CatalogTag {
  work_count: number;
}

export interface TagAggregatePage {
  items: TagAggregate[];
  next_cursor: string | null;
}

export type TagDetail = TagAggregate;

export interface TagAssociationNode {
  tag_name: string;
  tag_translation: string | null;
  sampled_work_count: number;
}

export interface TagAssociationEdge {
  left: TagAssociationNode;
  right: TagAssociationNode;
  cooccurrence_work_count: number;
  sample_support_basis_points: number;
  jaccard_basis_points: number;
  pmi_milli_bits: number;
}

export interface TagAssociationGraphResponse {
  interpretation: "descriptive_association_only";
  semantic_classification_performed: false;
  catalog_work_count: number;
  sampled_work_count: number;
  sample_truncated: boolean;
  observed_tag_count: number;
  eligible_edge_count: number;
  result_truncated: boolean;
  anchor_tag: string | null;
  minimum_cooccurrence: number;
  edges: TagAssociationEdge[];
}

export interface TagSensitivityPoint {
  minimum_cooccurrence: number;
  eligible_edge_count: number;
  returned_edge_count: number;
  baseline_edge_retention_basis_points: number;
  stability_comparable: boolean;
}

export interface TagReviewCandidate {
  rank: number;
  left_tag_name: string;
  left_tag_translation: string | null;
  right_tag_name: string;
  right_tag_translation: string | null;
  cooccurrence_work_count: number;
  sample_support_basis_points: number;
  jaccard_basis_points: number;
  pmi_milli_bits: number;
  survives_minimum_cooccurrence: number[];
  review_state: "pending_human_review";
}

export interface TagAssociationSensitivityResponse {
  interpretation: "descriptive_association_only";
  semantic_classification_performed: false;
  catalog_work_count: number;
  sampled_work_count: number;
  sample_truncated: boolean;
  anchor_tag: string | null;
  thresholds: number[];
  baseline_edge_count: number;
  baseline_result_truncated: boolean;
  points: TagSensitivityPoint[];
  review_candidates: TagReviewCandidate[];
}

export interface WorkMetricSnapshot {
  observed_at: string;
  public_view_count: number | null;
  public_bookmark_count: number | null;
  public_like_count: number | null;
}

export interface WorkMetricHistoryPage {
  work_id: string;
  items: WorkMetricSnapshot[];
  next_cursor: string | null;
}

export interface DailyMetricTrend {
  day: string;
  observed_work_count: number;
  total_public_view_count: number;
  total_public_bookmark_count: number;
  total_public_like_count: number;
}

export interface DailyMetricTrendResponse {
  date_from: string;
  date_to: string;
  items: DailyMetricTrend[];
}

export interface WorkRankingItem {
  work_id: string;
  work_title: string;
  author_id: string;
  author_display_name: string;
  score: number;
}

export interface WorkRankingPage {
  metric: "likes" | "bookmarks" | "views";
  items: WorkRankingItem[];
  next_cursor: string | null;
}

export type EntityType = "work" | "author" | "tag_page" | "search_page";
export type SchemaStatus = "discovered" | "approved" | "rejected";

export interface SchemaDefinitionSummary {
  id: number;
  entity_type: EntityType;
  fingerprint: string;
  sample_count: number;
  status: SchemaStatus;
  compatible_parser_min: string | null;
  compatible_parser_max: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SchemaDefinitionPage {
  items: SchemaDefinitionSummary[];
  next_cursor: string | null;
}

export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";

export interface OperationalRun {
  id: number;
  run_type: string;
  provider: string;
  status: RunStatus;
  task_count: number;
  succeeded_task_count: number;
  failed_task_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface OperationalRunPage {
  items: OperationalRun[];
  next_cursor: string | null;
}

export type TaskStatus =
  "pending" | "running" | "succeeded" | "failed" | "cancelled";

export interface OperationalTask {
  id: number;
  run_id: number;
  task_type: string;
  status: TaskStatus;
  priority: number;
  attempt_count: number;
  last_error_code: string | null;
  available_at: string;
  updated_at: string;
}

export interface OperationalTaskPage {
  items: OperationalTask[];
  next_cursor: string | null;
}

export type QuarantineStatus = "open" | "resolved" | "ignored";

export interface QuarantineSummary {
  id: number;
  entity_type: EntityType;
  error_code: string;
  status: QuarantineStatus;
  first_failed_at: string;
  last_failed_at: string;
}

export interface QuarantineSummaryPage {
  items: QuarantineSummary[];
  next_cursor: string | null;
}

export interface ConsumerSecurityStatus {
  shared_rate_limit_backend: "postgres" | "disabled";
  durable_access_audit_sink: "postgres" | "structured_log";
  identity_adapter_configured: boolean;
  external_publication_approved: false;
  rate_limit_window_count: number;
  audit_event_count: number;
  oldest_audit_at: string | null;
  latest_audit_at: string | null;
  audit_retention_days: number;
}

export type JjwxcNovelStatus = "连载" | "完结" | "暂停" | "锁定" | "未知";
export type JjwxcNovelSort =
  "reviews" | "favorites" | "points" | "words" | "clicks";
export type JjwxcAuthorSort = "favorites" | "reviews" | "points" | "novels";

export interface JjwxcNovel {
  novel_id: string;
  title: string;
  author_id: string;
  author_display_name: string;
  novel_type: string;
  perspective: string | null;
  status: JjwxcNovelStatus;
  word_count: number;
  review_count: number;
  favorite_count: number;
  points: number;
  average_non_v_chapter_click_count: number | null;
  average_v_chapter_click_count: number | null;
  non_v_chapter_count: number;
  v_chapter_count: number;
  chapter_click_coverage_count: number;
  synopsis_char_count: number | null;
  synopsis_sentence_count: number | null;
  synopsis_theme_terms: string[];
  tags: string[];
  observed_at: string;
  source_mode: "synthetic_fixture" | "public_candidate";
}

export interface JjwxcOverview {
  data_mode: "synthetic_fixture" | "database_snapshot";
  novel_count: number;
  author_count: number;
  total_word_count: number;
  total_review_count: number;
  total_favorite_count: number;
  click_coverage_count: number;
  synopsis_feature_coverage_count: number;
  latest_observed_at: string;
}

export interface JjwxcNovelPage {
  data_mode: "synthetic_fixture" | "database_snapshot";
  sort: JjwxcNovelSort;
  items: JjwxcNovel[];
  total: number;
}

export interface JjwxcSearchResponse {
  data_mode: "synthetic_fixture" | "database_snapshot";
  query: string;
  match_fields: ["title", "author_display_name"];
  items: JjwxcNovel[];
  total: number;
  limit: number;
  offset: number;
}

export interface JjwxcCatalogSearchItem {
  novel_id: string;
  title: string;
  author_id: string;
  author_display_name: string;
  novel_type: string;
  status: JjwxcNovelStatus;
  word_count: number;
  points: number;
  published_at: string | null;
  last_seen_at: string;
  detail_available: boolean;
}

export interface JjwxcFullCatalogSearchResponse {
  data_mode: "synthetic_fixture" | "database_snapshot";
  query: string;
  coverage: "progressive_official_bookbase_index";
  match_fields: ["title", "author_display_name"];
  items: JjwxcCatalogSearchItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface JjwxcChannelRankingItem {
  rank: number;
  novel_id: string;
  title: string;
  author_id: string | null;
  author_display_name: string | null;
  observed_at: string;
}

export interface JjwxcChannelRankingResponse {
  ranking_key: "channel_gold" | "newcomer";
  label: string;
  observation_day: string | null;
  items: JjwxcChannelRankingItem[];
}

export interface JjwxcAuthorSummary {
  author_id: string;
  author_display_name: string;
  novel_count: number;
  total_word_count: number;
  total_review_count: number;
  total_favorite_count: number;
  total_points: number;
}

export interface JjwxcAuthorPage {
  data_mode: "synthetic_fixture" | "database_snapshot";
  sort: JjwxcAuthorSort;
  items: JjwxcAuthorSummary[];
}

export interface JjwxcAuthorDetail {
  author: JjwxcAuthorSummary;
  novels: JjwxcNovel[];
}

export interface JjwxcTrendPoint {
  day: string;
  observed_novel_count: number;
  total_review_count: number;
  total_favorite_count: number;
  total_points: number;
  total_word_count: number;
  click_coverage_count: number;
  mean_non_v_chapter_click_count: number | null;
  v_click_coverage_count: number;
  mean_v_chapter_click_count: number | null;
}

export interface JjwxcTrendResponse {
  data_mode: "synthetic_fixture" | "database_snapshot";
  items: JjwxcTrendPoint[];
}

export type JjwxcMetricName =
  "reviews" | "favorites" | "points" | "words" | "clicks" | "synopsis_chars";

export type JjwxcTimelineMetricName = Exclude<
  JjwxcMetricName,
  "synopsis_chars"
>;

export interface JjwxcMetricSummary {
  metric: JjwxcMetricName;
  label: string;
  observed_count: number;
  missing_count: number;
  coverage_basis_points: number;
  minimum: number | null;
  maximum: number | null;
  mean: number | null;
  median: number | null;
  standard_deviation: number | null;
  p25: number | null;
  p75: number | null;
  coefficient_of_variation: number | null;
}

export interface JjwxcCorrelationCell {
  x_metric: JjwxcMetricName;
  y_metric: JjwxcMetricName;
  paired_count: number;
  coefficient: number | null;
}

export interface JjwxcNormalizedTrendPoint {
  day: string;
  values: Record<JjwxcTimelineMetricName, number | null>;
}

export interface JjwxcMultivariateResponse {
  data_mode: "synthetic_fixture" | "database_snapshot";
  history_source: "project_snapshot_fixture" | "canonical_database_snapshot";
  interpretation: "descriptive_association_only";
  click_definition: "average_non_v_chapter_click_count";
  timeline: JjwxcTrendPoint[];
  normalized_timeline: JjwxcNormalizedTrendPoint[];
  summaries: JjwxcMetricSummary[];
  correlation_matrix: JjwxcCorrelationCell[];
}

export type JjwxcRatingMetric =
  | "reviews"
  | "favorites"
  | "points"
  | "words"
  | "clicks";

export type JjwxcRatingGrade = "SSS" | "SS" | "S" | "A" | "B";

export interface JjwxcRatingItem {
  entity_id: string;
  title: string;
  author_display_name: string;
  score_basis_points: number;
  grade: JjwxcRatingGrade;
  coverage_basis_points: number;
  component_scores: Record<JjwxcRatingMetric, number | null>;
}

export interface JjwxcRatingResponse {
  data_mode: "synthetic_fixture" | "database_snapshot";
  model_version: "jjwxc-public-performance-v1";
  interpretation: "cohort_relative_public_data_performance";
  selected_day: string;
  available_days: string[];
  default_weights: Record<JjwxcRatingMetric, number>;
  effective_weights: Record<JjwxcRatingMetric, number>;
  novels: JjwxcRatingItem[];
  authors: JjwxcRatingItem[];
}
