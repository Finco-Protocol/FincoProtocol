import React from "react";
import { workbookHref, workbookModules } from "./catalog";
import "./workbook.css";

export default function WorkbookNavigation({ active, onSelect }: { active: string; onSelect?: (id: string) => void }) {
  function select(id: string) {
    const entry = workbookModules.find(m => m.id === id);
    if (onSelect && !entry?.destination) onSelect(id);
    else window.location.assign(workbookHref(id));
  }
  return <aside className="fm-wb-navigation" aria-label="Workbook sheets">
    <div className="fm-wb-tree-title">FINCO workbook <span>DEMO</span></div>
    <label className="fm-wb-mobile-picker">Workbook sheet
      <select aria-label="Workbook sheet" value={active} onChange={e => select(e.target.value)}>
        {Array.from(new Set(workbookModules.map(m => m.family))).map(family => <optgroup key={family} label={family}>{workbookModules.filter(m => m.family === family).map(m => <option key={m.id} value={m.id}>{m.label} · {m.state}</option>)}</optgroup>)}
      </select>
    </label>
    <nav className="fm-wb-tree" aria-label="FINCO workbook sheets">
      {Array.from(new Set(workbookModules.map(m => m.family))).map(family => <div key={family}>
        <h2>{family}</h2>
        {workbookModules.filter(m => m.family === family).map(m => <a key={m.id} href={workbookHref(m.id)} aria-current={active === m.id ? "page" : undefined}
          onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            select(m.id);
          }}>
          <span>{m.label}</span><small>{m.state === "Interactive demo" ? "Demo" : m.state === "Visual mock" ? "Mock" : "Gated"}</small>
        </a>)}
      </div>)}
    </nav>
    <p className="fm-wb-authority">Module presence follows the supplied main inventory. Release authority is not independently verified. “Demo” is not a production-availability claim.</p>
  </aside>;
}
