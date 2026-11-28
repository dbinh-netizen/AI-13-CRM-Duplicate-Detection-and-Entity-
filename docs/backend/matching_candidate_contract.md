# Matching candidate contract

The matching pipeline returns candidate evidence for backend review; scoring a
pair does not create, activate, or write an identity link.

## Candidate preview

`GET /api/candidates` returns the existing `candidates` collection. Each
candidate includes:

- `similarity_score`, `proposed_category`, and `review_state`
- `left_record_id` and `right_record_id`, which disambiguate duplicate source
  keys in the CSV preview; these identify source file rows and are not database
  primary keys
- `evidence`: per-attribute evidence with `direction`, source values,
  explanation, and `rule_version`
- `conflict_flags` (also retained as `conflicts` for existing clients)
- `identity_link_blocked` and `identity_link_activated` (`false` for candidate
  generation)
- `rule_version`: `2.0-IDENTITY-SAFETY`

Clients must not interpret a high similarity score as an approval. A company
and branch sharing a tax root are a related-but-distinct candidate, and
conflicting authoritative tax identifiers or entity roles prevent identity
activation.

The W04 `#PAIR-002` case came from a duplicate `ACC001` source key: UI lookup by
`source_key` selected the later Sao Mai row instead of the matching Ánh Dương
row. The preview now resolves records by the file-and-row `record_id`, so the
displayed records correspond to the pair that was actually scored.

## Scoring and review safety

The structured matching pipeline exposes attribute-level evidence, conflict
codes, `identity_link_blocked`, and the scoring policy version on
`PairScoringResult`. A conflicting tax identifier within the same identity
role is negative evidence; a shared tax root across different roles is not a
tax-ID match.

Candidate clusters are formed only when every pair in the cluster has direct
candidate support above the configured score threshold and no blocking
conflict evidence. Pairwise links are checked again before canonical
activation. Therefore, A-B and B-C similarity alone cannot establish A-C.
For the CSV preview, a candidate with a blocking conflict is also capped below
the configured high-confidence threshold.

Canonical activation remains a separate, explicitly approved review action.
Matching and candidate generation never invoke activation.
