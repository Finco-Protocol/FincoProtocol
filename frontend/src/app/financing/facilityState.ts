// A DRAFT Senior facility with no commitment and no draws is a placeholder, not terms: it must read "not configured", never zero.
export const isUnconfiguredFacility = (row: { status?: string; commitment_keur?: number | null; draws_total_keur?: number | null }): boolean =>
  row.status === "DRAFT" && !row.commitment_keur && !row.draws_total_keur;

/** The reserve row of the "Not released" list is about a reserve FACILITY inside a multi-instrument structure.  Reserve settings of the single
 *  Senior loan live in Bankability (released policies only), so the two panels must say the same thing about what is available. */
export const unsupportedReason = (row: { name: string; reason: string }): string =>
  /^DSRA/i.test(row.name)
    ? "A reserve facility inside a multi-instrument structure is not released: reserve support must be NONE there. Reserve settings for the single Senior loan are in Bankability (released policies only)."
    : row.reason;
