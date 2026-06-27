export type UserRole = "admin" | "researcher";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  created_at: string;
}

export interface AIDetectionRulePreferences {
  phrases: string[];
  phrase_count: number;
  rule_source: "default_app_rules" | "user_custom_rules";
  updated_at: string | null;
}

export type AIDetectionRuleType = "phrase" | "regex" | "semantic" | "hybrid";
export type AIDetectionRuleSeverity = "low" | "medium" | "high";
export type AIDetectionRuleScope = "user" | "global";
export type AIDetectionConditionScope = "sentence" | "paragraph" | "document";
export type AIDetectionAnalyzeMode = "fast" | "deep" | "rule_only";

export interface AIDetectionRuleAction {
  flag: boolean;
  message?: string | null;
}

export interface PhraseRuleCondition {
  kind: "phrase" | "phrase_group";
  phrase?: string | null;
  phrases: string[];
  threshold: number;
  scope: AIDetectionConditionScope;
}

export interface RegexRuleCondition {
  kind: "regex";
  pattern: string;
  threshold: number;
  scope: AIDetectionConditionScope;
  flags?: Array<"IGNORECASE" | "MULTILINE" | "DOTALL">;
}

export interface SemanticRuleCondition {
  kind: "semantic";
  instruction: string;
  threshold: AIDetectionRuleSeverity;
  scope: AIDetectionConditionScope;
}

export interface MetricRuleCondition {
  kind: "metric";
  metric:
    | "sentence_uniformity_above"
    | "type_token_ratio_below"
    | "transition_density_above"
    | "repetition_score_above";
  value: number;
  scope: AIDetectionConditionScope;
}

export interface MissingCitationRuleCondition {
  kind: "missing_citation";
  scope: AIDetectionConditionScope;
  min_words: number;
  threshold: number;
}

export interface RepeatedStructureRuleCondition {
  kind: "repeated_structure";
  scope: AIDetectionConditionScope;
  threshold: number;
}

export type AIDetectionRuleCondition =
  | PhraseRuleCondition
  | RegexRuleCondition
  | SemanticRuleCondition
  | MetricRuleCondition
  | MissingCitationRuleCondition
  | RepeatedStructureRuleCondition;

export interface CompiledAIDetectionRule {
  name: string;
  description?: string | null;
  rule_type: AIDetectionRuleType;
  severity: AIDetectionRuleSeverity;
  weight: number;
  conditions: AIDetectionRuleCondition[];
  operator: "AND" | "OR";
  action: AIDetectionRuleAction;
}

export interface AIDetectionRule {
  id: string;
  owner_id: string | null;
  name: string;
  description: string | null;
  source_text: string;
  rule_type: AIDetectionRuleType;
  severity: AIDetectionRuleSeverity;
  weight: number;
  enabled: boolean;
  scope: AIDetectionRuleScope;
  rule_json: CompiledAIDetectionRule;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AIDetectionRuleCompileResponse {
  compiled_rule: CompiledAIDetectionRule;
  warnings: string[];
}

export interface AIDetectionAnalyzeRequest {
  text: string;
  mode?: AIDetectionAnalyzeMode;
  use_custom_rules?: boolean;
  rule_ids?: string[] | null;
  include_explanation?: boolean;
}

export interface AIDetectionMatchedRuleLocation {
  scope: AIDetectionConditionScope;
  paragraph_index?: number | null;
  sentence_index?: number | null;
  start?: number | null;
  end?: number | null;
}

export interface AIDetectionMatchedRule {
  rule_id: string;
  rule_name: string;
  rule_type: string;
  severity: AIDetectionRuleSeverity;
  weight: number;
  matched_text?: string | null;
  reason: string;
  confidence?: number | null;
  location?: AIDetectionMatchedRuleLocation | null;
}

export interface AIDetectionEvidence {
  text: string;
  reason: string;
  rule_id: string;
  severity: AIDetectionRuleSeverity;
  paragraph_index?: number | null;
}

export interface AIDetectionResult {
  type: "ai_detection";
  mode: AIDetectionAnalyzeMode;
  score: number;
  model_score?: number | null;
  roberta_score?: number | null;
  custom_rule_score: number;
  final_score: number;
  rule_score: number;
  risk_level: AIDetectionRuleSeverity;
  confidence: string;
  verdict: string;
  method: string;
  flags: string[];
  details: Record<string, unknown>;
  detectors_used: string[];
  skipped_detectors: string[];
  fallback_reason?: string | null;
  rule_source: "default_app_rules" | "user_custom_rules";
  matched_rules: Array<AIDetectionMatchedRule | string>;
  evidence: AIDetectionEvidence[];
  explanation?: string | null;
  suggestions: string[];
  disclaimer: string;
  warnings: string[];
}

export interface Session {
  id: string;
  title: string;
  mode: "auto" | "general_qa" | "verification" | "journal_match" | "retraction" | "ai_detection";
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  message_type:
    | "text"
    | "citation_report"
    | "journal_list"
    | "retraction_report"
    | "pdf_summary"
    | "ai_writing_detection"
    | "grammar_report"
    | "file_upload";
  content: string | null;
  tool_results: Record<string, unknown> | unknown[] | null;
  created_at: string;
}

export interface CitationCandidate {
  source?: string;
  title?: string | null;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  url?: string | null;
  external_id?: string | null;
  external_id_type?: string | null;
  score?: number | null;
  missing_fields?: string[];
  source_domain?: string | null;
}

export interface CitationItem {
  citation: string;
  status: string;
  evidence?: string | null;
  doi?: string | null;
  title?: string | null;
  authors?: string[];
  year?: number | null;
  source?: string | null;
  confidence?: number;
  verification_mode?: string | null;
  input_doi?: string | null;
  matched_doi?: string | null;
  input_identifier?: string | null;
  input_identifier_type?: string | null;
  matched_identifier?: string | null;
  matched_identifier_type?: string | null;
  matched_title?: string | null;
  matched_year?: number | null;
  matched_authors?: string[];
  matched_venue?: string | null;
  candidates?: CitationCandidate[];
  warning?: string | null;
  evidence_breakdown?: Record<string, number> | null;
  reason?: string | null;
  field_evidence?: Record<string, unknown> | null;
  source_diagnostics?: Record<string, unknown> | null;
  parse_status?: string | null;
  search_attempted?: boolean;
  search_strategy?: string | null;
  metadata_consistency?: string | null;
  completed_metadata?: Record<string, unknown> | null;
  formatted_apa?: string | null;
  formatted_bibtex?: string | null;
  csl_json?: Record<string, unknown> | null;
  resolved_url?: string | null;
  evidence_urls?: string[];
  resolver_chain?: string[];
  candidate_gap?: number | null;
  matched_by?: string | null;
  index?: number;
  raw_citation?: string | null;
  ux_group?: "verified" | "review" | "problem" | "temporary_issue" | string;
  short_issue?: string | null;
  suggested_action?: string | null;
  discovered_from?: string | null;
  source_domain?: string | null;
  web_search_query?: string | null;
  web_search_provider?: string | null;
  web_search_skipped_reason?: string | null;
  source_type?: string | null;
  source_number?: number | null;
}

export interface CitationBatchSummary {
  total_count: number;
  verified_count: number;
  review_count: number;
  problem_count: number;
  temporary_issue_count: number;
  status_counts: Record<string, number>;
  summary_text?: string | null;
  default_summary_text?: string | null;
}

export interface CitationReportPayload {
  type: "citation_report";
  data?: CitationItem[];
  results?: CitationItem[];
  summary?: CitationBatchSummary;
  text?: string;
  statistics?: Record<string, unknown>;
  no_citation_found?: boolean;
}

export interface DoiAuthorDetail {
  given?: string | null;
  family?: string | null;
  name?: string | null;
}

export interface DoiMetadataData {
  doi?: string | null;
  title?: string | null;
  abstract?: string | null;
  year?: number | null;
  publication_year?: number | null;
  venue?: string | null;
  journal?: string | null;
  publisher?: string | null;
  authors?: string[] | null;
  author_details?: DoiAuthorDetail[] | null;
  author_count?: number | null;
  subjects?: string[] | null;
  keywords?: string[] | null;
  research_field?: string | null;
  research_field_basis?: string | null;
  research_field_note?: string | null;
  main_topic?: string | null;
  main_topic_basis?: string | null;
  main_topic_note?: string | null;
  url?: string | null;
  verification_status?: string | null;
  confidence?: number | null;
  source?: string | null;
  missing_fields?: string[] | null;
  notes?: string[] | null;
}

export interface DoiMetadataResult {
  type: "doi_metadata";
  status?: string;
  requested_field?: string | null;
  data?: DoiMetadataData;
}

export interface ToolResultGroup {
  tool_name?: string;
  label?: string;
  type: string;
  data: unknown;
  summary?: string;
}

export interface MultiToolReportPayload {
  type: "multi_tool_report";
  groups: ToolResultGroup[];
}

export interface ScholarlyRecord {
  entity_type?: string;
  source?: string | null;
  confidence?: number | null;
  match_status?: string | null;
  score?: number | null;
  title?: string;
  abstract?: string | null;
  snippet?: string | null;
  venue?: string | null;
  year?: string | number | null;
  doi?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  pmid?: string | null;
  pmcid?: string | null;
  url?: string | null;
  authors?: string[];
  subjects?: string[];
  keywords?: string[];
}

export interface CheckedSourceItem {
  name?: string;
  state?: string;
  detail?: string | null;
  candidate_count?: number;
}

export interface AuthorPublicationAuthor {
  name?: string;
  orcid?: string | null;
  external_ids?: {
    openalex?: string | null;
  };
  confidence?: number | null;
  identity_status?: string | null;
  checked_sources?: CheckedSourceItem[];
  publications?: ScholarlyRecord[];
  publication_count?: number;
  notes?: string[];
}

export interface AuthorPublicationSearchPayload {
  type: "author_publication_search";
  status?: string;
  query?: string;
  author?: {
    name?: string | null;
    matched_from_context?: boolean;
    source_paper_doi?: string | null;
    source_paper_title?: string | null;
  } | null;
  source_doi?: string | null;
  source_title?: string | null;
  source_record?: ScholarlyRecord | null;
  authors?: AuthorPublicationAuthor[];
  external_search_used?: boolean;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  checked_sources?: CheckedSourceItem[];
  notes?: string[];
}

export interface ChatCompletionResponse {
  session_id: string;
  session: Session;
  user_message: Message;
  assistant_message: Message;
}

export interface FileAttachment {
  id: string;
  session_id: string;
  message_id: string | null;
  user_id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  storage_key: string;
  storage_url: string;
  storage_encrypted: boolean;
  storage_encryption_alg: string | null;
  created_at: string;
}

export interface FileUploadResponse {
  id: string;
  session_id: string;
  message_id: string | null;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  storage_url: string;
  storage_encrypted: boolean;
  storage_encryption_alg: string | null;
  created_at: string;
}

export interface AdminOverview {
  users: number;
  sessions: number;
  messages: number;
  files: number;
  total_storage_bytes: number;
  total_storage_mb: number;
  active_admins: number;
  active_researchers: number;
}

export interface StorageHealth {
  status: string;
  storage_type: string;
  accessible: boolean;
  details?: Record<string, unknown>;
  error?: string;
}

export interface StorageStats {
  storage_type: string;
  total_objects: number;
  total_size_bytes: number;
  total_size_mb: number;
  bucket_name: string | null;
  local_path: string | null;
  health_status: string;
}

export interface JournalMetrics {
  impact_factor?: number | null;
  h_index?: number | null;
  review_time_weeks?: number | null;
  acceptance_rate?: number | null;
  open_access?: boolean | null;
  citescore?: number | null;
  sjr_quartile?: string | null;
  jcr_quartile?: string | null;
  indexed_scopus?: boolean | null;
  indexed_wos?: boolean | null;
}

export interface JournalLink {
  label: string;
  url: string;
  type: string;
}

export interface JournalMatchItem {
  id?: string | null;
  name?: string | null;
  journal: string;
  venue_id?: string | null;
  venue_type?: string | null;
  score?: number | null;
  reason?: string | null;
  subject_fit?: string | null;
  publisher?: string | null;
  url?: string | null;
  issn?: string | null;
  eissn?: string | null;
  links?: JournalLink[];
  link_warning?: string | null;
  supporting_evidence?: Array<{
    entity_type?: string;
    title?: string;
    doi?: string | null;
    publication_year?: number | null;
    url?: string | null;
  }>;
  warning_flags?: string[];
  metric_provenance?: Record<string, string>;
  unverified_metrics?: string[];
  metrics?: JournalMetrics;
}

export interface JournalMatchPayload {
  type: "journal_match";
  matches: JournalMatchItem[];
  request_id?: string | null;
  candidate_ids?: string[];
  status?: string;
  source_fields?: Record<string, string>;
  confidence?: "low" | "medium" | "high" | null;
  warning?: string | null;
  debug?: Record<string, unknown>;
}

export interface ApiErrorShape {
  detail?: string;
  [key: string]: unknown;
}
