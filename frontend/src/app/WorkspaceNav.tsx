import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

export type WorkspaceSection =
  | "overview" | "inputs" | "statements" | "results" | "analysis"
  | "financing" | "scenarios" | "diagnostics" | "trust";

/** Order and numbering follow the approved FINCO Model section model. */
export const WORKSPACE_SECTIONS: ReadonlyArray<{ id: WorkspaceSection; label: string; number: string }> = [
  { id: "inputs", label: "Inputs", number: "01" },
  { id: "statements", label: "Statements", number: "02" },
  { id: "financing", label: "Financing", number: "03" },
  { id: "results", label: "Results", number: "04" },
  { id: "scenarios", label: "Scenarios", number: "05" },
  { id: "analysis", label: "Analysis", number: "06" },
  { id: "diagnostics", label: "Model checks", number: "07" },
  { id: "trust", label: "Trust", number: "08" },
];

export const SECTION_LABELS: Record<WorkspaceSection, string> = {
  overview: "Overview",
  ...Object.fromEntries(WORKSPACE_SECTIONS.map((s) => [s.id, s.label])),
} as Record<WorkspaceSection, string>;

const SECTION_IDS = ["overview", ...WORKSPACE_SECTIONS.map((s) => s.id)] as WorkspaceSection[];

export function isWorkspaceSection(value: string): value is WorkspaceSection {
  return (SECTION_IDS as string[]).includes(value);
}

/**
 * Section navigation for the live workspace.  Every item is a real in-page link
 * (`#section`) so open-in-new-tab, copy-link, Back/Forward and refresh behave;
 * unmodified primary clicks are routed through `onNavigate` without a reload.
 *
 * Narrow screens (U03): the row scrolls horizontally inside its own box, never the page.
 * Overflow is shown (edge fades, a count and scroll buttons), the active destination is
 * scrolled into view, a focused link scrolls into view, and Left/Right/Home/End move
 * focus between destinations (Tab and Enter keep working).  Every destination stays a
 * real link in the DOM, so none is hidden.
 */
export function WorkspaceNav({ active, onNavigate }: { active: WorkspaceSection; onNavigate: (section: WorkspaceSection) => void }) {
  const navRef = useRef<HTMLElement>(null);
  const [overflow, setOverflow] = useState({ left: false, right: false });

  const measure = useCallback(() => {
    const nav = navRef.current;
    if (!nav) return;
    const left = nav.scrollLeft > 1;
    const right = nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1;
    setOverflow((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  const reveal = useCallback((link: Element | null | undefined, inline: ScrollLogicalPosition) => {
    const nav = navRef.current;
    if (!nav || !link) return;
    const box = link.getBoundingClientRect();
    const bounds = nav.getBoundingClientRect();
    if (box.left >= bounds.left && box.right <= bounds.right) return;
    // Scroll the nav box only: scrollIntoView could also move the page.
    const target = inline === "center"
      ? nav.scrollLeft + (box.left - bounds.left) - (bounds.width - box.width) / 2
      : box.left < bounds.left ? nav.scrollLeft - (bounds.left - box.left) - 12 : nav.scrollLeft + (box.right - bounds.right) + 12;
    nav.scrollTo({ left: Math.max(0, target), behavior: "auto" });
  }, []);

  // For a moment after the active destination changes, layout may still shift (scroll buttons appear): keep it in view.
  const settling = useRef(false);
  useEffect(() => {
    settling.current = true;
    reveal(navRef.current?.querySelector("a.active"), "center");
    measure();
    const timer = window.setTimeout(() => { settling.current = false; }, 500);
    return () => window.clearTimeout(timer);
  }, [active, reveal, measure]);

  // Showing / hiding a scroll button changes the width of the row: keep the focused link in view afterwards.
  useEffect(() => {
    const focused = document.activeElement;
    if (focused && navRef.current?.contains(focused)) reveal(focused, "nearest");
    else if (settling.current) reveal(navRef.current?.querySelector("a.active"), "center");
  }, [overflow.left, overflow.right, reveal]);

  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  const go = (event: MouseEvent<HTMLAnchorElement>, id: WorkspaceSection) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(id);
  };

  const move = (event: KeyboardEvent<HTMLAnchorElement>) => {
    const links = Array.from(navRef.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []);
    const index = links.indexOf(event.currentTarget);
    const next = event.key === "ArrowRight" ? index + 1 : event.key === "ArrowLeft" ? index - 1
      : event.key === "Home" ? 0 : event.key === "End" ? links.length - 1 : -1;
    if (next < 0 || index < 0) return;
    event.preventDefault();
    links[Math.max(0, Math.min(links.length - 1, next))].focus();
  };

  const scrollBy = (direction: -1 | 1) => {
    const nav = navRef.current;
    if (nav) nav.scrollBy({ left: direction * Math.max(120, nav.clientWidth * 0.6), behavior: "auto" });
  };

  const position = WORKSPACE_SECTIONS.findIndex((item) => item.id === active) + 1;
  return (
    <div className="rx-nav-wrap" data-nav-overflow-left={overflow.left || undefined} data-nav-overflow-right={overflow.right || undefined}>
      <div className="rx-nav-box">
        <button type="button" className="rx-nav-scroll rx-nav-scroll-left" aria-hidden="true" tabIndex={-1}
          data-nav-scroll="left" hidden={!overflow.left} onClick={() => scrollBy(-1)}>‹</button>
        <nav ref={navRef} className="fm-nav" aria-label="Model sections" data-workspace-nav="true" onScroll={measure}>
          {WORKSPACE_SECTIONS.map(({ id, label, number }) => (
            <a
              key={id}
              href={`#${id}`}
              className={active === id ? "active" : ""}
              aria-current={active === id ? "page" : undefined}
              onClick={(event) => go(event, id)}
              onKeyDown={move}
              onFocus={(event) => reveal(event.currentTarget, "nearest")}
            >
              <span className="fm-nav-num">{number}</span>{label}
            </a>
          ))}
        </nav>
        <button type="button" className="rx-nav-scroll rx-nav-scroll-right" aria-hidden="true" tabIndex={-1}
          data-nav-scroll="right" hidden={!overflow.right} onClick={() => scrollBy(1)}>›</button>
      </div>
      <p className="rx-nav-position" aria-hidden="true" data-nav-position="true">
        {position > 0 ? `${position} of ${WORKSPACE_SECTIONS.length} sections` : `${WORKSPACE_SECTIONS.length} sections`}
        {overflow.right ? " · swipe or scroll for more" : ""}
      </p>
    </div>
  );
}
