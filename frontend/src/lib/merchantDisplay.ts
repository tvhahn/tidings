/**
 * Display-layer cleanup of raw bank-statement merchant strings.
 *
 * This is presentation only — stored transaction data, API payloads, and the
 * original parsed email are never modified. Callers apply their own
 * title-casing on top of the returned value; this function deliberately
 * preserves the casing of whatever survives the cleaning rules.
 */
export function cleanMerchantName(raw: string): string {
  // 1. Trim.
  const original = raw.trim();
  if (!original) return "";

  let result = original;

  // 2. Strip one leading payment-processor prefix (one only). The `*`-style
  //    prefix ("SQ *", "PAYPAL *", WooCommerce's "WC*", Intuit's "IN *") wins;
  //    otherwise fall back to the whitespace-delimited form
  //    ("SP HARBOUR BEAN COFFEE"). The whitespace requirement keeps
  //    "Spotify"/"Sport Chek" untouched.
  const starPrefix = /^(?:sq|tst|py|pp|paypal|zelle|wc|in)\s*\*\s*/i;
  const wordPrefix = /^(?:sq|sp|tst)\s+/i;
  if (starPrefix.test(result)) {
    result = result.replace(starPrefix, "");
  } else {
    result = result.replace(wordPrefix, "");
  }

  // 3. Iteratively strip trailing store-identifier tokens (max 2 passes):
  //    bare/#-prefixed digits ("Northwind Foods 8802", "Wal-mart #8801", phone
  //    suffixes like "Starbucks 8007827282") and letter-then-digit codes
  //    ("Costco Wholesale W880", "Spotify P22015bdfe").
  const trailingDigits = /[\s\-–—]+#?\d{1,10}$/;
  const trailingCode = /\s+[A-Za-z]\d[A-Za-z0-9]*$/;
  for (let i = 0; i < 2; i++) {
    if (trailingDigits.test(result)) {
      result = result.replace(trailingDigits, "");
    } else if (trailingCode.test(result)) {
      result = result.replace(trailingCode, "");
    } else {
      break;
    }
  }

  // 4. Strip trailing orphaned punctuation left behind by the passes above
  //    ("Fuelstop@ -" → "Fuelstop").
  result = result.replace(/[@\-–—*\s]+$/, "");

  // 5. Collapse internal whitespace runs to single spaces.
  result = result.replace(/\s+/g, " ").trim();

  // 6. Guard against over-stripping: too little left, keep the trimmed original.
  if (result.length < 2) return original;

  return result;
}
