// INPUT SERIALISATION ONLY — a port of the Legacy F4 editor (static/js/investor_f4.js).  Percent becomes the typed fraction, a
// blank number becomes null (the server then refuses it), and the version rule is the Legacy one: the saved agreement's next
// version when the id is unchanged, otherwise 1.  The server (`parse_terms` / `save_agreement`) is the only validator.
export interface InvestorRow { investorId: string; ownershipPct: string; commitment: string }
export interface ContributionRow { investorId: string; cashDate: string; amount: string }
export interface AgreementDraft { agreementId: string; investors: InvestorRow[]; contributions: ContributionRow[] }

const numberOrNull = (text: string): number | null => (text === "" ? null : Number(text));

export function serializeAgreement(d: AgreementDraft, saved: { agreementId: string; nextVersion: number }): string {
  return JSON.stringify({
    schema_version: 1, agreement_id: d.agreementId,
    version: d.agreementId === saved.agreementId ? saved.nextVersion : 1,
    currency: "EUR", unit: "kEUR", policy: "RESIDUAL_ONLY",
    investors: d.investors.map((r) => {
      const fraction = numberOrNull(r.ownershipPct);
      return { investor_id: r.investorId, ownership_fraction: typeof fraction === "number" ? fraction / 100 : fraction, commitment_keur: numberOrNull(r.commitment), investment_class: "COMMON_EQUITY" };
    }),
    contributions: d.contributions.map((r) => ({ investor_id: r.investorId, cash_date: r.cashDate, amount_keur: numberOrNull(r.amount) })),
  });
}

/** The draft a user starts from: the saved agreement (percent for display) or an empty one. */
export function draftFromTerms(terms: { agreement_id: string; investors: Array<{ investor_id: string; ownership_fraction: number; commitment_keur: number }>;
                                        contributions: Array<{ investor_id: string; cash_date: string; amount_keur: number }> } | null): AgreementDraft {
  if (!terms) return { agreementId: "", investors: [], contributions: [] };
  return {
    agreementId: terms.agreement_id,
    investors: terms.investors.map((i) => ({ investorId: i.investor_id, ownershipPct: String(i.ownership_fraction * 100), commitment: String(i.commitment_keur) })),
    contributions: terms.contributions.map((c) => ({ investorId: c.investor_id, cashDate: c.cash_date, amount: String(c.amount_keur) })),
  };
}

export const isSame = (a: AgreementDraft, b: AgreementDraft): boolean => JSON.stringify(a) === JSON.stringify(b);
