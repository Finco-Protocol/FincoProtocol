import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { INPUT_DESTINATIONS, type WorkspaceDestination } from "./workspaceNavigation";

export function WorkspaceSidebar({ active, onNavigate }: {
  active: WorkspaceDestination;
  onNavigate: (destination: WorkspaceDestination) => void;
}) {
  const [open, setOpen] = useState(false);
  const nav = useRef<HTMLElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (nav.current?.contains(document.activeElement) && toggle.current?.getClientRects().length) toggle.current.focus();
    setOpen(false);
  }, [active]);
  function keys(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); return; }
    if (!(event.target instanceof HTMLAnchorElement)) return;
    const links = Array.from(nav.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []).filter((link) => link.getClientRects().length);
    const index = links.indexOf(event.target);
    const next = event.key === "ArrowDown" ? Math.min(index + 1, links.length - 1)
      : event.key === "ArrowUp" ? Math.max(index - 1, 0)
      : event.key === "Home" ? 0 : event.key === "End" ? links.length - 1 : -1;
    if (next >= 0) { event.preventDefault(); links[next]?.focus(); }
  }
  const link = (destination: WorkspaceDestination, label: string) => <a key={destination} href={`#${destination}`}
    aria-current={active === destination ? "page" : undefined} data-workspace-destination={destination}
    onClick={(event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); onNavigate(destination);
    }}>{label}</a>;
  return <aside className="wsv2-sidebar" data-workspace-sidebar="true">
    <button ref={toggle} type="button" className="rx-button rx-button-secondary wsv2-menu" aria-expanded={open}
      aria-controls="wsv2-navigation" onClick={() => {
        setOpen(!open);
        if (!open) window.requestAnimationFrame(() => nav.current?.querySelector<HTMLAnchorElement>("a[aria-current], a")?.focus());
      }}>Model sections <span aria-hidden="true">{open ? "−" : "+"}</span></button>
    <nav id="wsv2-navigation" ref={nav} aria-label="Financial workspace" className={open ? "is-open" : ""} onKeyDown={keys}>
      {link("overview", "Overview")}
      <details open><summary>Inputs</summary>
        {Object.entries(INPUT_DESTINATIONS).map(([key, item]) => link(`inputs/${key}` as WorkspaceDestination, item.label))}
        {link("financing", "Financing / Equity")}
      </details>
      <details open><summary>Outputs & analysis</summary>
        {link("statements", "Statements")}{link("results", "Results / Run history")}
        {link("scenarios", "Scenarios")}{link("analysis", "Analysis / Credit")}
      </details>
      <details open><summary>Checks & reporting</summary>
        {link("diagnostics", "Model checks")}{link("trust", "Trust / Reporting")}
      </details>
    </nav>
  </aside>;
}
