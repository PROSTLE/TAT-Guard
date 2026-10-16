-- Pass 4: fuzzy candidates for CBS DEBITS that carry no usable reference.
-- Candidates: transactions with no debit matched yet, not a business decline, same amount,
-- CBS posting within [switch ts, switch ts + pass4_window_s]. Score (weights in RECON.SETTINGS):
--   amount (always 1 here) * w_amount + payee-bank token found in narration * w_bank + time closeness * w_time.
-- Auto-match only mutual-best pairs with score >= pass4_threshold. Everything else goes to the human queue.
INSERT INTO "RECON"."CBS_MATCH"
WITH cfg AS (
  SELECT MAX(CASE WHEN "PARAM_NAME" = 'pass4_window_s' THEN CAST("PARAM_VALUE" AS DECIMAL(18,0)) END) AS "WIN",
         MAX(CASE WHEN "PARAM_NAME" = 'pass4_threshold' THEN CAST("PARAM_VALUE" AS DECIMAL(9,4)) END) AS "THR",
         MAX(CASE WHEN "PARAM_NAME" = 'pass4_w_amount' THEN CAST("PARAM_VALUE" AS DECIMAL(9,4)) END) AS "W_AMT",
         MAX(CASE WHEN "PARAM_NAME" = 'pass4_w_bank_token' THEN CAST("PARAM_VALUE" AS DECIMAL(9,4)) END) AS "W_BANK",
         MAX(CASE WHEN "PARAM_NAME" = 'pass4_w_time' THEN CAST("PARAM_VALUE" AS DECIMAL(9,4)) END) AS "W_TIME"
  FROM "RECON"."SETTINGS"
),
dr AS (  -- unmatched CBS debits
  SELECT r.* FROM "RECON"."CBS_REF" r
  WHERE r."DR_CR" = 'DR'
    AND NOT EXISTS (SELECT 1 FROM "RECON"."CBS_MATCH" m WHERE m."CBS_ENTRY_ID" = r."CBS_ENTRY_ID")
),
tx AS (  -- transactions that should have a debit but have none matched
  SELECT t.* FROM "RECON"."TXN" t
  WHERE NOT EXISTS (SELECT 1 FROM "RECON"."CBS_MATCH" m WHERE m."RRN" = t."RRN" AND m."KIND" = 'DEBIT')
    AND NOT EXISTS (SELECT 1 FROM "RECON"."RESP_CODE_MAP" rc
                    WHERE rc."RESP_CODE" = COALESCE(t."SW_RESP", t."NPCI_RESP") AND rc."CATEGORY" = 'BUSINESS_DECLINE')
),
cand AS (
  SELECT dr."CBS_ENTRY_ID", tx."UPI_TXN_ID", tx."RRN", dr."AMOUNT_PAISE", dr."POST_TS",
         cfg."W_AMT"
         + CASE WHEN tx."PAYEE_BANK" IS NOT NULL AND INSTR(dr."NARRATION", tx."PAYEE_BANK") > 0 THEN cfg."W_BANK" ELSE 0 END
         + cfg."W_TIME" * (1 - SECONDS_BETWEEN(dr."POST_TS", tx."SW_TS") / cfg."WIN") AS "SCORE",
         cfg."THR"
  FROM dr JOIN tx ON tx."AMOUNT_PAISE" = dr."AMOUNT_PAISE"
  CROSS JOIN cfg
  WHERE SECONDS_BETWEEN(dr."POST_TS", tx."SW_TS") BETWEEN 0 AND cfg."WIN"
),
ranked AS (
  SELECT c.*,
         ROW_NUMBER() OVER (PARTITION BY "CBS_ENTRY_ID" ORDER BY "SCORE" DESC, "RRN") AS "RN_C",
         ROW_NUMBER() OVER (PARTITION BY "RRN" ORDER BY "SCORE" DESC, "CBS_ENTRY_ID") AS "RN_T",
         COUNT(*) OVER (PARTITION BY "CBS_ENTRY_ID") AS "N_CAND"
  FROM cand c
)
SELECT "CBS_ENTRY_ID", "UPI_TXN_ID", "RRN", 'DEBIT', "AMOUNT_PAISE", "POST_TS", 4, CAST("SCORE" AS DECIMAL(5,4))
FROM ranked
WHERE "RN_C" = 1 AND "RN_T" = 1 AND "SCORE" >= "THR";
