import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { WORKSPACE_NAV_GROUPS, activeNavigationDestination, type WorkspaceDestination } from "./workspaceNavigation";

export function WorkspaceSidebar({ active, onNavigate }: {
  active: WorkspaceDestination;
  onNavigate: (destination: WorkspaceDestination) => void;
}) {
  const [open, setOpen] = useState(false);
  const nav = useRef<HTMLElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  // Close before the new route is painted; a passive effect can close a newly reopened menu.
  useLayoutEffect(() => {
    if (nav.current?.contains(document.activeElement) && toggle.current?.getClientRects().length) toggle.current.focus();
    setOpen(false);
  }, [active]);
  useLayoutEffect(() => {
    if (open) nav.current?.querySelector<HTMLAnchorElement>("a[aria-current], a")?.focus();
  }, [open]);
  function keys(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); return; }
    if (!(event.target instanceof HTMLAnchorElement)) return;
    const links = Array.from(nav.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []).filter((link) => link.getClientRects().length);
    const index = links.indexOf(event.target);
    const next = (event.key === "ArrowDown" || event.key === "ArrowRight") ? Math.min(index + 1, links.length - 1)
      : (event.key === "ArrowUp" || event.key === "ArrowLeft") ? Math.max(index - 1, 0)
      : event.key === "Home" ? 0 : event.key === "End" ? links.length - 1 : -1;
    if (next >= 0) { event.preventDefault(); links[next]?.focus(); }
  }
  const link = (destination: WorkspaceDestination, label: string) => <a key={destination} href={`#${destination}`}
    className={activeNavigationDestination(active) === destination ? "active" : undefined}
    aria-current={activeNavigationDestination(active) === destination ? "page" : undefined} data-workspace-destination={destination}
    onClick={(event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); setOpen(false); onNavigate(destination);
    }}>{label}</a>;
  return <aside className="wsv2-sidebar" data-workspace-sidebar="true">
    <button ref={toggle} type="button" className="rx-button rx-button-secondary wsv2-menu" aria-expanded={open}
      aria-controls="wsv2-navigation" onClick={() => {
        setOpen((previous) => !previous);
      }}>Model sections <span aria-hidden="true">{open ? "−" : "+"}</span></button>
    <nav id="wsv2-navigation" ref={nav} aria-label="Financial workspace" data-workspace-nav="true" className={`fm-nav${open ? " is-open" : ""}`} onKeyDown={keys}>
      {WORKSPACE_NAV_GROUPS.map((group) => <section className="ux-nav-group" key={group.label} aria-label={group.label}>
        <h2>{group.destination ? link(group.destination, group.label) : group.label}</h2>
        {group.items.map((item) => link(item.destination, item.label))}
      </section>)}
    </nav>
  </aside>;
}
