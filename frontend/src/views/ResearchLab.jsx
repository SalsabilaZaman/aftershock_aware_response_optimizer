import React from 'react';
import assumptions from '../../../pipelines/model_assumptions.json';

function AssumptionTable({ items }) {
  return <div className="table-scroll"><table className="data assumption-table"><thead><tr><th>Parameter</th><th>Value</th><th>Meaning</th></tr></thead>
    <tbody>{items.map((item) => <tr key={item.name}><td>{item.name}</td><td>{item.value}{item.unit && item.unit !== '—' ? <div className="muted">{item.unit}</div> : null}</td><td>{item.detail}</td></tr>)}</tbody>
  </table></div>;
}

export default function ResearchLab({ model }) {
  const selectedModel = assumptions.models.find((entry) => entry.id === model);

  return <section className="assumptions-layout">
    <div className="panel assumptions-panel">
      <h3>Common assumptions</h3>
      <p className="muted">Values below describe settings shared across the pipeline.</p>
      {assumptions.shared.map((group) => <div key={group.group}>
        <h4>{group.group}</h4><AssumptionTable items={group.items} />
      </div>)}
    </div>

    <div className="panel assumptions-panel">
      <h3>Selected model assumptions</h3>
      {/* <p className="muted">“Not modeled” means the selected model does not include that mechanism.</p> */}
      {selectedModel
        ? <div className="assumption-model">
          <h4>{selectedModel.name}</h4>
          <p className="muted">{selectedModel.summary}</p>
          <AssumptionTable items={selectedModel.items} />
        </div>
        : <p className="muted">No assumptions are available for this model.</p>}
    </div>
  </section>;
}
