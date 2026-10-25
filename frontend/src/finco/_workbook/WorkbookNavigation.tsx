import {
  workbookAreaForModule,
  workbookAreaLabels,
  workbookHref,
  workbookModulesForArea,
  workbookSelectedModule,
  type WorkbookArea,
} from "./catalog";
import "./workbook.css";

export default function WorkbookNavigation({ active, activeArea, onSelect }: {
  active: string;
  activeArea?: WorkbookArea;
  onSelect?: (id: string) => void;
}) {
  const area = activeArea || workbookAreaForModule(active);
  const entries = workbookModulesForArea(area);
  const selected = workbookSelectedModule(active);

  function select(id: string) {
    const entry = entries.find(m => m.id === id);
    if (onSelect && !entry?.destination) onSelect(id);
    else window.location.assign(workbookHref(id));
  }
  return <aside className="fm-wb-navigation" aria-label={`${workbookAreaLabels[area]} pages`}>
    <div className="fm-wb-tree-title">{workbookAreaLabels[area]}</div>
    <label className="fm-wb-mobile-picker">Choose a page
      <select aria-label={`Choose a ${workbookAreaLabels[area]} page`} value={selected} onChange={e => select(e.target.value)}>
        {entries.map(module => <option key={module.id} value={module.id}>
          {module.label}{module.state === "Unavailable" ? " — Not yet available" : module.state === "Visual mock" ? " — Preview" : ""}
        </option>)}
      </select>
    </label>
    <nav className="fm-wb-tree" aria-label={`${workbookAreaLabels[area]} pages`}>
      <h2>{workbookAreaLabels[area]}</h2>
      {entries.map(m => <a key={m.id} href={workbookHref(m.id)} aria-current={selected === m.id ? "page" : undefined}
          onKeyDown={event => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            select(m.id);
          }}
          onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            select(m.id);
          }}>
          <span>{m.label}</span>
          {m.state === "Unavailable" && <small>Not yet available</small>}
          {m.state === "Visual mock" && <small>Preview</small>}
      </a>)}
    </nav>
    <p className="fm-wb-authority">Sample figures are illustrative. Available pages do not calculate financial results.</p>
  </aside>;
}
