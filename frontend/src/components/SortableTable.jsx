import React, { useMemo, useState } from 'react';
import { downloadCsv } from '../format.js';

// Hand-rolled sortable/filterable table — no table library. 411 rows renders
// fine unvirtualized in a scrollable container, so this stays simple:
// click-to-sort headers, a text filter, CSV export, sticky header via CSS.
//
// columns: [{ key, label, align: 'left'|'right', value: (row) => any,
//             render?: (row) => node, sortValue?: (row) => number|string }]
export default function SortableTable({ columns, rows, filterPlaceholder = 'Filter…', csvFilename, rowKey, onRowClick, defaultSort = null }) {
  const [sort, setSort] = useState(defaultSort); // { key, dir }
  const [filter, setFilter] = useState('');

  const filtered = useMemo(() => {
    if (!filter.trim()) return rows;
    const q = filter.trim().toLowerCase();
    return rows.filter((r) =>
      columns.some((c) => String(c.value(r) ?? '').toLowerCase().includes(q)),
    );
  }, [rows, filter, columns]);

  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return filtered;
    const getVal = col.sortValue ?? col.value;
    const copy = [...filtered];
    copy.sort((a, b) => {
      const av = getVal(a);
      const bv = getVal(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return av.localeCompare(bv);
      return av - bv;
    });
    if (sort.dir === 'desc') copy.reverse();
    return copy;
  }, [filtered, sort, columns]);

  const toggleSort = (key) => {
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: 'asc' };
      if (s.dir === 'asc') return { key, dir: 'desc' };
      return null;
    });
  };

  const sortIndicator = (key) => {
    if (!sort || sort.key !== key) return '';
    return sort.dir === 'asc' ? ' ▲' : ' ▼';
  };

  return (
    <div>
      <div className="table-toolbar">
        <input
          className="table-filter"
          type="text"
          placeholder={filterPlaceholder}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter table rows"
        />
        <span className="table-count num">{sorted.length.toLocaleString()} rows</span>
        {csvFilename && (
          <button
            className="btn-ghost"
            onClick={() =>
              downloadCsv(
                csvFilename,
                columns.map((c) => ({ label: c.label, value: c.value })),
                sorted,
              )
            }
          >
            Export CSV
          </button>
        )}
      </div>
      {sorted.length === 0 && <div className="notice info">No rows match this filter.</div>}
      <div className="table-scroll">
        <table className="data sortable">
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={c.align === 'right' ? 'num' : ''}
                  onClick={() => toggleSort(c.key)}
                  tabIndex={0}
                  role="button"
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleSort(c.key)}
                >
                  {c.label}
                  {sortIndicator(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={rowKey(r)}
                className={onRowClick ? 'clickable' : ''}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={() => onRowClick?.(r)}
                onKeyDown={(e) => onRowClick && (e.key === 'Enter') && onRowClick(r)}
              >
                {columns.map((c) => (
                  <td key={c.key} className={c.align === 'right' ? 'num' : ''}>
                    {c.render ? c.render(r) : c.value(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
