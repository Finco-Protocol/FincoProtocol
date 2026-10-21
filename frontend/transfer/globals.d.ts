// Type surface for the sandbox transfer-entry window flags.  The Replit source
// package declares these on window without a TypeScript surface; the harvested
// harness declares them here so the dev-only entry typechecks.
interface Window {
  __FINCO_TRANSFER_APP__?: boolean;
  __FINCO_TRANSFER_BASE__?: string;
}
