// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Story 7.2 — POST /marketplace/templates/import-draft (Core-verified only).

/** Closed failure codes from Core `verify_template_manifest` + draft rules. */
export type MarketplaceImportDraftErrorCode =
  | 'PARSE'
  | 'SCHEMA'
  | 'SIGNATURE'
  | 'PINS'
  | 'draft_agent_count_exceeded';

export interface MarketplaceRealmDraft {
  agent_count: number;
  realm_description: string;
  adapter_hint: string | null;
  policy_refs: Array<Record<string, unknown>>;
}

export interface MarketplaceImportDraftSuccess {
  schema_version: number;
  draft: MarketplaceRealmDraft;
}
