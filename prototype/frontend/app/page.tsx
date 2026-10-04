"use client";

import { useEffect, useMemo, useState } from 'react';

const API = '/api/backend';

type StateValue =
  | 'VERIFIED_STOPPED'
  | 'STILL_ACTIVE'
  | 'UNKNOWN'
  | 'EXCEPTION'
  | 'CONFLICTED'
  | 'PENDING';

type EvidenceStatus = 'DIRECT' | 'INFERRED' | 'CONTESTED' | 'STALE' | 'ABSENT' | 'UNVERIFIED';
type TimelineCategory = 'All' | 'Consent' | 'Processing' | 'Audience' | 'Export' | 'Processor' | 'Contradictions';

type Customer = { customer_id: string; name: string; synthetic_demo: boolean };
type EvidenceReference = {
  evidence_id: string;
  source_type: string;
  source_record: string;
  source_url?: string | null;
  timestamp?: string | null;
  evidence_status: EvidenceStatus;
  raw_excerpt?: string | null;
};
type Finding = {
  asset: string;
  asset_type: string;
  finding_state: StateValue;
  reason: string;
  evidence: EvidenceReference[];
  event_time?: string | null;
  observed_time?: string | null;
  source_system?: string | null;
  contradictory_evidence: string[];
  recommended_action?: string | null;
};
type Investigation = {
  investigation_id: string;
  customer_id: string;
  customer_name: string;
  purpose: string;
  withdrawal_timestamp: string;
  watermark: string;
  overall_investigation_state: string;
  first_break?: string | null;
  remediation_summary?: string | null;
  findings: Finding[];
};
type GraphNode = { id: string; label: string; kind: string; state?: StateValue | null; timestamp?: string | null };
type GraphPath = { nodes: GraphNode[]; edges: Array<{ from: string; to: string; relationship: string }> };
type EvidenceDetail = EvidenceReference & {
  observed_time?: string | null;
  ingested_at?: string | null;
  integrity_hash?: string | null;
  source_system?: string | null;
};
type TimelineEntry = { evidence: EvidenceReference; finding: Finding };
type SandboxInfo = {
  enabled: boolean;
  environment: string;
  organization_id: string;
  organization_name: string;
  person: { person_ref: string; name: string };
  purpose: string;
  scenarios: Array<{ scenario_id: string; name: string; description: string }>;
  systems: string[];
};
type SandboxEvent = {
  event_id: string;
  event_type: string;
  source_system: string;
  event_time?: string | null;
  ingested_at?: string | null;
  status: 'accepted' | 'duplicate' | 'rejected' | 'failed';
  http_status?: number;
  projection_status?: string | null;
  evidence_id?: string | null;
  message?: string | null;
};
type SandboxRun = {
  run_id: string;
  scenario_id: string;
  scenario_name: string;
  status: string;
  events: SandboxEvent[];
};

const DEMO_ORGANIZATION_ID = 'org-acmepay-demo';

const states: StateValue[] = [
  'STILL_ACTIVE',
  'UNKNOWN',
  'EXCEPTION',
  'CONFLICTED',
  'PENDING',
  'VERIFIED_STOPPED',
];

const stateMeta: Record<StateValue, { label: string; summaryLabel: string; glyph: string; description: string }> = {
  VERIFIED_STOPPED: {
    label: 'VERIFIED STOPPED',
    summaryLabel: 'Verified stopped',
    glyph: '✓',
    description: 'Evidence supports cessation.',
  },
  STILL_ACTIVE: {
    label: 'STILL ACTIVE',
    summaryLabel: 'Active processing',
    glyph: '!',
    description: 'Post-withdrawal processing evidence exists.',
  },
  UNKNOWN: {
    label: 'UNKNOWN',
    summaryLabel: 'Unknown',
    glyph: '?',
    description: 'Evidence is insufficient to establish the state.',
  },
  EXCEPTION: {
    label: 'EXCEPTION',
    summaryLabel: 'Exceptions',
    glyph: 'E',
    description: 'An organization-declared exception is present.',
  },
  CONFLICTED: {
    label: 'CONFLICTED',
    summaryLabel: 'Conflicted',
    glyph: '↯',
    description: 'Evidence sources contradict one another.',
  },
  PENDING: {
    label: 'PENDING',
    summaryLabel: 'Pending',
    glyph: '…',
    description: 'The observation window is incomplete.',
  },
};

const evidenceStatusHelp: Record<EvidenceStatus, string> = {
  DIRECT: 'A direct source record was observed.',
  INFERRED: 'Interpretation depends on an indirect relationship.',
  CONTESTED: 'The evidence is disputed by another source.',
  STALE: 'The record may be outside the current observation window.',
  ABSENT: 'An expected record was not found; absence alone does not prove an event did not occur.',
  UNVERIFIED: 'The source or record has not been independently verified.',
};

const navItems = [
  { label: 'Investigations', target: 'investigation' },
  { label: 'Evidence', target: 'findings' },
  { label: 'Data Lineage', target: 'processing-path' },
  { label: 'Systems', target: 'findings' },
  { label: 'Sources', target: 'timeline' },
  { label: 'Scenarios', target: 'remediation' },
  { label: 'Audit Log', target: 'timeline' },
];

const timelineCategories: TimelineCategory[] = [
  'All',
  'Consent',
  'Processing',
  'Audience',
  'Export',
  'Processor',
  'Contradictions',
];

const formatDate = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Kolkata',
  }).format(date);
};

const summarizeStateCounts = (findings: Finding[] = []): Record<StateValue, number> => {
  const counts = Object.fromEntries(states.map((state) => [state, 0])) as Record<StateValue, number>;
  for (const finding of findings) counts[finding.finding_state] += 1;
  return counts;
};

const latestEvidenceTime = (finding?: Finding | null) => {
  if (!finding) return null;
  const latest = finding.evidence
    .map((evidence) => evidence.timestamp)
    .filter((timestamp): timestamp is string => Boolean(timestamp))
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0];
  return latest || finding.event_time || null;
};

const getFindingForNode = (node: GraphNode, findings: Finding[]) => {
  const aliases: Record<string, string> = {
    'Customer Database': 'Customer Database / CRM',
    CRM: 'Customer Database / CRM',
  };
  const asset = aliases[node.label] || node.label;
  return findings.find((finding) => finding.asset === asset);
};

const timelineCategory = (finding: Finding): TimelineCategory => {
  if (finding.contradictory_evidence.length || finding.evidence.some((item) => item.evidence_status === 'CONTESTED')) {
    return 'Contradictions';
  }
  if (finding.asset_type === 'Audience') return 'Audience';
  if (finding.asset_type === 'Export') return 'Export';
  if (finding.asset_type === 'Processor') return 'Processor';
  if (finding.asset_type === 'Consent' || finding.asset === 'Customer Database / CRM') return 'Consent';
  return 'Processing';
};

function StateBadge({ state }: { state: StateValue }) {
  const meta = stateMeta[state];
  return (
    <span className={`state-badge state-${state}`}>
      <span className="state-glyph" aria-hidden="true">{meta.glyph}</span>
      <span>{meta.label}</span>
    </span>
  );
}

export default function HomePage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [purposeOptions, setPurposeOptions] = useState<string[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState('C1024');
  const [selectedPurpose, setSelectedPurpose] = useState('MARKETING');
  const [customerSearch, setCustomerSearch] = useState('');
  const [globalSearch, setGlobalSearch] = useState('');
  const [result, setResult] = useState<Investigation | null>(null);
  const [graph, setGraph] = useState<GraphPath | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [evidenceDetail, setEvidenceDetail] = useState<EvidenceDetail | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [actionNotice, setActionNotice] = useState('');
  const [backendStatus, setBackendStatus] = useState<'Checking' | 'Connected' | 'Unavailable'>('Checking');
  const [graphStatus, setGraphStatus] = useState<'Checking' | 'Connected' | 'Unavailable'>('Checking');
  const [selectedState, setSelectedState] = useState<StateValue | null>(null);
  const [timelineFilter, setTimelineFilter] = useState<TimelineCategory>('All');
  const [remediationResult, setRemediationResult] = useState<Investigation | null>(null);
  const [sandboxInfo, setSandboxInfo] = useState<SandboxInfo | null>(null);
  const [sandboxRun, setSandboxRun] = useState<SandboxRun | null>(null);
  const [sandboxScenarioId, setSandboxScenarioId] = useState('stale-etl-snapshot');
  const [sandboxLoading, setSandboxLoading] = useState(false);
  const [activeOrganizationId, setActiveOrganizationId] = useState(DEMO_ORGANIZATION_ID);

  const selectedCustomer = customers.find((customer) => customer.customer_id === selectedCustomerId);
  const filteredCustomers = useMemo(() => {
    const term = customerSearch.trim().toLowerCase();
    return customers.filter((customer) => !term
      || customer.customer_id.toLowerCase().includes(term)
      || customer.name.toLowerCase().includes(term));
  }, [customers, customerSearch]);

  useEffect(() => {
    let active = true;
    const loadMetadata = async () => {
      try {
        const [customerResponse, purposeResponse, healthResponse, sandboxResponse] = await Promise.all([
          fetch(`${API}/customers`),
          fetch(`${API}/purposes`),
          fetch(`${API}/health`),
          fetch(`${API}/api/v1/sandbox`),
        ]);
        if (!customerResponse.ok || !purposeResponse.ok || !healthResponse.ok || !sandboxResponse.ok) {
          throw new Error('The backend metadata or health check could not be loaded.');
        }
        const customerData: Customer[] = await customerResponse.json();
        const purposeData: string[] = await purposeResponse.json();
        const healthData = await healthResponse.json();
        const sandboxData: SandboxInfo = await sandboxResponse.json();
        if (!active) return;
        setCustomers(customerData);
        setPurposeOptions(purposeData);
        setSandboxInfo(sandboxData);
        if (customerData.length && !customerData.some((customer) => customer.customer_id === selectedCustomerId)) {
          setSelectedCustomerId(customerData[0].customer_id);
        }
        if (purposeData.length && !purposeData.includes(selectedPurpose)) setSelectedPurpose(purposeData[0]);
        setBackendStatus(healthData.database?.reachable ? 'Connected' : 'Unavailable');
        setGraphStatus(healthData.neo4j?.reachable ? 'Connected' : 'Unavailable');
        if (sandboxData.enabled) {
          const eventsResponse = await fetch(`${API}/api/v1/sandbox/events`);
          if (!eventsResponse.ok) throw new Error('The DemoCorp sandbox event monitor could not be loaded.');
          const eventsData: { events: SandboxEvent[] } = await eventsResponse.json();
          if (!active) return;
          if (eventsData.events.length) {
            setSandboxRun({
              run_id: 'existing-sandbox-run',
              scenario_id: '',
              scenario_name: 'Existing DemoCorp sandbox events',
              status: 'persisted',
              events: eventsData.events,
            });
          }
        }
      } catch (cause) {
        if (!active) return;
        setBackendStatus('Unavailable');
        setGraphStatus('Unavailable');
        setError(cause instanceof Error ? cause.message : 'Backend status could not be checked.');
      }
    };
    void loadMetadata();
    return () => { active = false; };
  // Initial metadata is loaded once; the initial selected values are intentional defaults.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openEvidence = async (evidenceId: string, finding?: Finding) => {
    if (finding) {
      setSelectedFinding(finding);
      setSelectedNode(null);
    }
    setEvidenceDetail(null);
    setEvidenceLoading(true);
    setError('');
    try {
      if (!result) throw new Error('Run an investigation before opening evidence.');
      const response = await fetch(`${API}/investigations/${result.investigation_id}/evidence/${encodeURIComponent(evidenceId)}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Evidence details are currently unavailable.');
      }
      setEvidenceDetail(await response.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Evidence details are currently unavailable.');
    } finally {
      setEvidenceLoading(false);
    }
  };

  const investigate = async (
    organizationId = activeOrganizationId,
    customerId = selectedCustomerId,
    purpose = selectedPurpose,
  ) => {
    if (!customerId || !purpose) {
      setError('Select a person and purpose before starting an investigation.');
      return;
    }
    setLoading(true);
    setError('');
    setActionNotice('');
    try {
      const response = await fetch(`${API}/investigations/withdrawal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_id: customerId, purpose, organization_id: organizationId }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'The investigation could not be completed.');
      }
      const payload: Investigation = await response.json();
      setActiveOrganizationId(organizationId);
      setSelectedCustomerId(customerId);
      setSelectedPurpose(purpose);
      setResult(payload);
      setSelectedState(null);
      setTimelineFilter('All');
      setSelectedFinding(null);
      setSelectedNode(null);
      setEvidenceDetail(null);

      const graphResponse = await fetch(`${API}/investigations/${encodeURIComponent(payload.investigation_id)}/graph`);
      if (!graphResponse.ok) {
        setGraph(null);
        setGraphStatus('Unavailable');
        throw new Error('The investigation was created, but its lineage projection could not be loaded.');
      }
      const graphPayload: GraphPath = await graphResponse.json();
      setGraph(graphPayload);
      setGraphStatus('Connected');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The investigation could not be completed.');
    } finally {
      setLoading(false);
    }
  };

  const startSandboxScenario = async () => {
    if (!sandboxInfo?.enabled) return;
    setSandboxLoading(true);
    setError('');
    setActionNotice('');
    try {
      const response = await fetch(`${API}/api/v1/sandbox/scenarios/${encodeURIComponent(sandboxScenarioId)}/run`, {
        method: 'POST',
      });
      const payload: SandboxRun = await response.json();
      setSandboxRun(payload);
      if (!response.ok || payload.status !== 'completed') {
        const failedEvent = [...(payload.events || [])].reverse().find((event) => event.status === 'failed' || event.status === 'rejected');
        throw new Error(failedEvent?.message || `The sandbox scenario did not complete (HTTP ${response.status}).`);
      }
      setActiveOrganizationId(sandboxInfo.organization_id);
      setSelectedCustomerId(sandboxInfo.person.person_ref);
      setSelectedPurpose(sandboxInfo.purpose);
      setActionNotice(`${payload.scenario_name} completed through ${payload.events.length} real ingestion API requests.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The sandbox scenario could not be completed.');
    } finally {
      setSandboxLoading(false);
    }
  };

  const resetSandbox = async () => {
    if (!sandboxInfo?.enabled || !window.confirm('Reset only the DemoCorp SANDBOX organization and its persisted events?')) return;
    setSandboxLoading(true);
    setError('');
    setActionNotice('');
    try {
      const response = await fetch(`${API}/api/v1/sandbox/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || payload.detail || 'The DemoCorp sandbox could not be reset.');
      setSandboxRun(null);
      setResult(null);
      setGraph(null);
      setSelectedFinding(null);
      setEvidenceDetail(null);
      setActiveOrganizationId(DEMO_ORGANIZATION_ID);
      setActionNotice('DemoCorp sandbox events, evidence, investigation scopes, and graph projection were reset.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The DemoCorp sandbox could not be reset.');
    } finally {
      setSandboxLoading(false);
    }
  };

  const simulateRemediation = async () => {
    if (!result) return;
    setError('');
    setActionNotice('');
    try {
      const response = await fetch(`${API}/investigations/remediation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ investigation_id: result.investigation_id, scenario: 'demo-remediation' }),
      });
      if (!response.ok) throw new Error('Remediation could not be simulated.');
      setRemediationResult(await response.json());
      setActionNotice('Remediation simulation complete. This changed no external systems.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Remediation simulation failed.');
    }
  };

  const findings = result?.findings ?? [];
  const stateCounts = summarizeStateCounts(findings);
  const firstBreak = findings.find((finding) => finding.asset === result?.first_break);
  const firstBreakEvidence = firstBreak?.evidence.find((item) => item.source_record === 'USE_STALE_CONSENT_SNAPSHOT')
    || firstBreak?.evidence[0];
  const visibleFindings = findings.filter((finding) => !selectedState || finding.finding_state === selectedState);
  const visibleNodes = (graph?.nodes ?? []).filter((node) => {
    if (!selectedState) return true;
    const canonicalFinding = getFindingForNode(node, findings);
    return canonicalFinding?.finding_state === selectedState;
  });
  const timelineEntries: TimelineEntry[] = findings.flatMap((finding) => (
    finding.evidence.map((evidence) => ({ evidence, finding }))
  ));
  const visibleTimeline = timelineEntries
    .filter(({ finding }) => !selectedState || finding.finding_state === selectedState)
    .filter(({ finding }) => timelineFilter === 'All' || timelineCategory(finding) === timelineFilter)
    .sort((left, right) => new Date(left.evidence.timestamp || 0).getTime() - new Date(right.evidence.timestamp || 0).getTime());

  const globalMatches = globalSearch.trim()
    ? [
      ...customers
        .filter((customer) => `${customer.customer_id} ${customer.name}`.toLowerCase().includes(globalSearch.trim().toLowerCase()))
        .map((customer) => ({ label: `${customer.customer_id} · ${customer.name}`, kind: 'Person', select: () => setSelectedCustomerId(customer.customer_id) })),
      ...(sandboxInfo?.enabled
        && `${sandboxInfo.person.person_ref} ${sandboxInfo.person.name}`.toLowerCase().includes(globalSearch.trim().toLowerCase())
        ? [{
          label: `${sandboxInfo.person.person_ref} · ${sandboxInfo.person.name}`,
          kind: 'SANDBOX person',
          select: () => void investigate(sandboxInfo.organization_id, sandboxInfo.person.person_ref, sandboxInfo.purpose),
        }]
        : []),
      ...(result && result.investigation_id.toLowerCase().includes(globalSearch.trim().toLowerCase())
        ? [{ label: result.investigation_id, kind: 'Investigation', select: () => document.getElementById('investigation')?.scrollIntoView({ behavior: 'smooth' }) }]
        : []),
      ...timelineEntries
        .filter(({ evidence }) => evidence.evidence_id.toLowerCase().includes(globalSearch.trim().toLowerCase()))
        .slice(0, 5)
        .map(({ evidence, finding }) => ({
          label: evidence.evidence_id,
          kind: 'Evidence',
          select: () => { void openEvidence(evidence.evidence_id, finding); },
        })),
    ].slice(0, 7)
    : [];

  const hasSandboxEvents = Boolean(sandboxRun?.events.some((event) => event.status === 'accepted' || event.status === 'duplicate'));
  const sandboxPanel = sandboxInfo?.enabled ? (
    <section className="sandbox-panel" aria-label="DemoCorp company sandbox">
      <div className="sandbox-panel-heading">
        <div>
          <span className="minor-label">CONTROLLED COMPANY SANDBOX</span>
          <h2>DemoCorp event stream</h2>
          <p>Synthetic events are sent sequentially through the same ingestion API used by company integrations.</p>
        </div>
        <span className="sandbox-environment">SANDBOX · {sandboxInfo.environment.toUpperCase()}</span>
      </div>
      <div className="sandbox-controls">
        <label htmlFor="sandboxScenario">Scenario</label>
        <select
          id="sandboxScenario"
          value={sandboxScenarioId}
          onChange={(event) => setSandboxScenarioId(event.target.value)}
          disabled={sandboxLoading || hasSandboxEvents}
        >
          {sandboxInfo.scenarios.map((scenario) => (
            <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name}</option>
          ))}
        </select>
        <button
          className="primary-button"
          type="button"
          onClick={() => void startSandboxScenario()}
          disabled={sandboxLoading || hasSandboxEvents}
        >
          {sandboxLoading ? 'Processing events…' : 'Run scenario'}
        </button>
        <button className="secondary-button" type="button" onClick={() => void resetSandbox()} disabled={sandboxLoading}>
          Reset sandbox
        </button>
      </div>
      <div className="sandbox-systems">
        <span>CONNECTED SYNTHETIC SYSTEMS</span>
        {sandboxInfo.systems.map((system) => <small key={system}>{system}</small>)}
      </div>
      {sandboxRun ? (
        <div className="sandbox-monitor">
          <div className="sandbox-monitor-heading">
            <div>
              <strong>{sandboxRun.scenario_name}</strong>
              <span>{sandboxRun.events.length} observed ingestion requests · {sandboxRun.status.toUpperCase()}</span>
            </div>
            <button
              className="text-button"
              type="button"
              onClick={() => void investigate(sandboxInfo.organization_id, sandboxInfo.person.person_ref, sandboxInfo.purpose)}
              disabled={!hasSandboxEvents || loading}
            >
              Investigate P-1001 →
            </button>
          </div>
          <div className="sandbox-event-list" role="table" aria-label="Sandbox event monitor">
            {sandboxRun.events.map((event) => (
              <div className="sandbox-event-row" role="row" key={event.event_id}>
                <span className={`sandbox-event-status status-${event.status}`}>{event.status}</span>
                <strong>{event.event_type}</strong>
                <span>{event.source_system}</span>
                <span>{formatDate(event.event_time)}</span>
                <small>{event.projection_status || event.message || event.event_id}</small>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="sandbox-empty">No sandbox events are currently recorded. Run one scenario, then investigate its persisted evidence.</p>
      )}
      {actionNotice ? <p className="action-notice" role="status">{actionNotice}</p> : null}
    </section>
  ) : null;

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand-block" href="#investigation" aria-label="CONSENTTRACE home">
          <span className="brand-mark" aria-hidden="true">C</span>
          <span>
            <span className="brand">CONSENTTRACE</span>
            <span className="brand-subtitle">Evidence-backed withdrawal investigation</span>
          </span>
        </a>

        <nav className="nav-list" aria-label="Main navigation">
          <div className="nav-section-label">WORKSPACE</div>
          {navItems.map((item, index) => (
            <a
              key={item.label}
              className={`nav-item ${index === 0 ? 'active' : ''}`}
              href={`#${item.target}`}
              aria-current={index === 0 ? 'page' : undefined}
            >
              <span className="nav-marker" aria-hidden="true">{['▦', '▤', '⌁', '▧', '◉', '↻', '≡'][index]}</span>
              {item.label}
            </a>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="demo-indicator">
            <span className="demo-light" aria-hidden="true" />
            <span>
              <strong>DEMO ENVIRONMENT</strong>
              <small>Synthetic data only</small>
            </span>
          </div>
          <div className="connection-list" aria-label="Service connectivity">
            <div className="connection-row">
              <span className={`connection-dot ${backendStatus === 'Connected' ? 'is-online' : ''}`} aria-hidden="true" />
              <span>Backend</span>
              <strong>{backendStatus}</strong>
            </div>
            <div className="connection-row">
              <span className={`connection-dot ${graphStatus === 'Connected' ? 'is-online' : ''}`} aria-hidden="true" />
              <span>Graph</span>
              <strong>{graphStatus}</strong>
            </div>
          </div>
          <div className="tenant-caption">{activeOrganizationId === sandboxInfo?.organization_id ? 'DEMOCORP · SANDBOX' : 'ACMEPAY · SYNTHETIC SCENARIO'}</div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumbs"><span>Privacy operations</span><span aria-hidden="true">/</span><strong>Investigations</strong></div>
          <div className="global-search">
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="Search person, investigation, or evidence ID"
              value={globalSearch}
              onChange={(event) => setGlobalSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && globalMatches[0]) globalMatches[0].select();
                if (event.key === 'Escape') setGlobalSearch('');
              }}
              placeholder="Search person / investigation / evidence ID"
            />
            {globalMatches.length > 0 ? (
              <div className="search-results" role="listbox" aria-label="Search results">
                {globalMatches.map((match, index) => (
                  <button
                    key={`${match.kind}-${match.label}-${index}`}
                    type="button"
                    role="option"
                    aria-selected="false"
                    onClick={() => { match.select(); setGlobalSearch(''); }}
                  >
                    <span>{match.label}</span><small>{match.kind}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="topbar-right">
            <span className="tenant-name">
              {activeOrganizationId === sandboxInfo?.organization_id ? 'DemoCorp' : 'AcmePay'}
              <small>{activeOrganizationId === sandboxInfo?.organization_id ? 'SANDBOX TENANT' : 'DEMO TENANT'}</small>
            </span>
            <span className="profile-avatar" aria-hidden="true">PO</span>
            <span className="profile-name">Privacy Ops</span>
          </div>
        </header>

        <main className="workspace">
          {!result ? (
            <section className="start-view" id="investigation">
              <div className="page-kicker">INVESTIGATION WORKSTATION</div>
              <h1>Consent withdrawn.<br /><span>Now prove where the data stopped.</span></h1>
              <p className="start-copy">
                Trace consent-dependent processing through downstream systems. Review each finding against its persisted evidence.
              </p>
              <div className="scenario-disclosure">
                <span className="disclosure-icon" aria-hidden="true">i</span>
                <span><strong>Synthetic AcmePay scenario</strong> · Demo data only. Backend persistence and graph projection are checked live.</span>
              </div>

              <div className="start-form">
                <div className="start-form-heading">
                  <div><span className="section-index">01</span><h2>Start an investigation</h2></div>
                  <span className="minor-label">WITHDRAWAL REVIEW</span>
                </div>
                <div className="selector-grid">
                  <div className="field-group">
                    <label htmlFor="customerSearch">Person</label>
                    <input
                      id="customerSearch"
                      value={customerSearch}
                      onChange={(event) => setCustomerSearch(event.target.value)}
                      placeholder="Search person or ID"
                    />
                    <div className="customer-list" aria-label="Person selection">
                      {filteredCustomers.length ? filteredCustomers.map((customer) => (
                        <button
                          key={customer.customer_id}
                          type="button"
                          className={`customer-option ${selectedCustomerId === customer.customer_id ? 'selected' : ''}`}
                          onClick={() => {
                            setSelectedCustomerId(customer.customer_id);
                            setActiveOrganizationId(DEMO_ORGANIZATION_ID);
                          }}
                        >
                          <span className="customer-initial" aria-hidden="true">{customer.customer_id.slice(-2)}</span>
                          <span><strong>{customer.customer_id}</strong><small>{customer.name}</small></span>
                          {selectedCustomerId === customer.customer_id ? <span className="selected-mark" aria-label="Selected">✓</span> : null}
                        </button>
                      )) : <div className="empty-inline">No person matches that search.</div>}
                    </div>
                  </div>
                  <div className="field-group purpose-field">
                    <label htmlFor="purposeSelect">Purpose under review</label>
                    <select id="purposeSelect" value={selectedPurpose} onChange={(event) => setSelectedPurpose(event.target.value)}>
                      {purposeOptions.map((purpose) => <option key={purpose} value={purpose}>{purpose}</option>)}
                    </select>
                    <div className="scenario-context">
                      <span className="context-label">DATA CONTEXT</span>
                      <strong>AcmePay · Synthetic scenario</strong>
                      <span>Scenario records are clearly identified as demo data throughout this workspace.</span>
                    </div>
                    <button className="primary-button start-button" type="button" onClick={() => void investigate()} disabled={loading || !customers.length}>
                      {loading ? 'Building investigation…' : 'Investigate withdrawal'}
                      <span aria-hidden="true">→</span>
                    </button>
                  </div>
                </div>
              </div>
              {sandboxPanel}
              {error ? <div className="inline-error" role="alert">{error}</div> : null}
            </section>
          ) : (
            <>
              <section className="investigation-heading" id="investigation">
                <div className="heading-topline">
                  <div className="page-kicker">INVESTIGATION</div>
                  <button className="text-button" type="button" onClick={() => { setResult(null); setGraph(null); setSelectedFinding(null); setSelectedNode(null); setEvidenceDetail(null); }}>
                    <span aria-hidden="true">←</span> New investigation
                  </button>
                </div>
                <div className="investigation-titleline">
                  <div>
                    <h1>{result.customer_id} <span>{result.purpose}</span></h1>
                    <p className="withdrawal-meta"><span className="withdrawal-dot" />Withdrawal detected · {formatDate(result.withdrawal_timestamp)}</p>
                  </div>
                  <div className="investigation-ref">
                    <span>INVESTIGATION ID</span>
                    <strong>{result.investigation_id}</strong>
                  </div>
                </div>
                <div className="primary-status">
                  <span className="status-mark" aria-hidden="true">!</span>
                  <div>
                    <strong>{result.overall_investigation_state.replaceAll('_', ' ')}</strong>
                    <p>Post-withdrawal processing evidence was observed in the evaluated evidence window.</p>
                  </div>
                  <div className="legal-note">Evidence investigation only — this result is not a legal compliance determination.</div>
                </div>
              </section>

              {sandboxPanel}

              <section className="workflow-strip" aria-label="Investigation workflow">
                {[
                  'Identify person',
                  'Select purpose',
                  'Review withdrawal',
                  'Trace processing',
                  'Inspect evidence',
                  'Locate first break',
                  'Verify remediation',
                  'Re-run investigation',
                ].map((step, index) => (
                  <div key={step} className={`workflow-step ${index < 6 ? 'complete' : ''} ${index === 5 ? 'current' : ''}`}>
                    <span>{index < 5 ? '✓' : String(index + 1).padStart(2, '0')}</span>{step}
                  </div>
                ))}
              </section>

              <section className="summary-section" aria-labelledby="summary-title">
                <div className="section-heading">
                  <div><span className="section-index">01</span><h2 id="summary-title">Investigation summary</h2></div>
                  <span className="summary-hint">{findings.length} findings · select a classification to filter</span>
                </div>
                <div className="summary-counts">
                  {states.map((state) => (
                    <button
                      key={state}
                      type="button"
                      className={`summary-count ${selectedState === state ? 'is-selected' : ''}`}
                      aria-pressed={selectedState === state}
                      title={stateMeta[state].description}
                      onClick={() => setSelectedState((current) => current === state ? null : state)}
                    >
                      <span className={`summary-symbol state-${state}`} aria-hidden="true">{stateMeta[state].glyph}</span>
                      <span className="summary-copy"><small>{stateMeta[state].summaryLabel}</small><strong>{stateCounts[state]}</strong></span>
                    </button>
                  ))}
                </div>
              </section>

              <section className="break-section" aria-labelledby="break-title">
                <div className="break-main">
                  <div className="break-heading">
                    <span className="break-overline"><span aria-hidden="true">◆</span> FIRST CONFIRMED BREAK</span>
                    {firstBreak ? <StateBadge state={firstBreak.finding_state} /> : null}
                  </div>
                  <h2 id="break-title">{firstBreak?.asset || result.first_break || 'No confirmed break identified'}</h2>
                  <p>{firstBreak?.reason || 'The evaluated evidence does not identify a confirmed downstream break.'}</p>
                  {firstBreak ? (
                    <div className="break-facts">
                      <div><span>Event time</span><strong>{formatDate(firstBreakEvidence?.timestamp || firstBreak.observed_time || firstBreak.event_time)}</strong></div>
                      <div><span>Evidence ID</span><button type="button" onClick={() => firstBreakEvidence && void openEvidence(firstBreakEvidence.evidence_id, firstBreak)}>{firstBreakEvidence?.evidence_id || '—'}</button></div>
                      <div><span>Source</span><strong>{firstBreak.asset || firstBreak.source_system || '—'}</strong></div>
                      <div><span>Evidence type</span><strong>{firstBreakEvidence?.source_record || firstBreakEvidence?.source_type || '—'}</strong></div>
                    </div>
                  ) : null}
                </div>
                <div className="break-actions">
                  <button type="button" className="primary-button" onClick={() => firstBreakEvidence && void openEvidence(firstBreakEvidence.evidence_id, firstBreak!)}>
                    View evidence
                  </button>
                  <button type="button" className="secondary-button" onClick={() => scrollTo('processing-path')}>View lineage</button>
                  <button type="button" className="secondary-button" onClick={() => scrollTo('remediation')}>Review action</button>
                </div>
              </section>

              <section className="section-block" id="processing-path">
                <div className="section-heading">
                  <div><span className="section-index">02</span><h2>Processing path</h2></div>
                  <span className="section-context">Evidence-associated assets · latest available record</span>
                </div>
                {graph ? (
                  <div className="path-track">
                    {visibleNodes.map((node, index) => {
                      const finding = getFindingForNode(node, findings);
                      const nodeState = finding?.finding_state ?? node.state;
                      return (
                        <div className="path-segment" key={node.id}>
                          <button
                            type="button"
                            className={`path-node ${nodeState ? `state-${nodeState}` : ''} ${node.label === result.first_break ? 'first-break-node' : ''}`}
                            onClick={() => {
                              setEvidenceDetail(null);
                              if (finding) {
                                setSelectedFinding(finding);
                                setSelectedNode(null);
                              } else {
                                setSelectedFinding(null);
                                setSelectedNode(node);
                              }
                            }}
                            aria-label={`${node.label}, ${finding?.asset_type || node.kind}, ${nodeState || 'state not available'}. Open ${finding ? 'finding evidence' : 'lineage context'}.`}
                          >
                            <span className="path-node-top"><span>{String(index + 1).padStart(2, '0')}</span>{node.label === result.first_break ? <small>FIRST BREAK</small> : null}</span>
                            <strong>{node.label}</strong>
                            <span className="path-kind">{finding?.asset_type || node.kind}</span>
                            {nodeState ? <StateBadge state={nodeState} /> : <span className="unavailable-state">Classification unavailable</span>}
                            <span className="path-node-footer">
                              <span>{formatDate(latestEvidenceTime(finding) || node.timestamp || (node.id === 'withdrawal' ? result.withdrawal_timestamp : null))}</span>
                              <span>{finding?.evidence.length ?? 0} evidence</span>
                            </span>
                          </button>
                          {index < visibleNodes.length - 1 ? <span className="path-connector" aria-hidden="true">→</span> : null}
                        </div>
                      );
                    })}
                    {visibleNodes.length === 0 ? <div className="empty-inline">No path nodes match this classification.</div> : null}
                  </div>
                ) : <div className="empty-inline">The lineage projection is not available for this investigation.</div>}
                <p className="lineage-caveat">Static lineage describes system relationships; it is not runtime evidence of processing.</p>
              </section>

              <section className="section-block findings-section" id="findings">
                <div className="section-heading">
                  <div><span className="section-index">03</span><h2>Findings</h2></div>
                  <div className="table-controls">
                    {selectedState ? <button type="button" className="text-button" onClick={() => setSelectedState(null)}>Clear {stateMeta[selectedState].summaryLabel} filter ×</button> : null}
                    <span className="section-context">{visibleFindings.length} of {findings.length} findings</span>
                  </div>
                </div>
                <div className="findings-table-wrap">
                  <table className="findings-table">
                    <thead><tr><th>Asset</th><th>Type</th><th>Classification</th><th>Why</th><th>Latest evidence</th></tr></thead>
                    <tbody>
                      {visibleFindings.map((finding) => (
                        <tr
                          key={finding.asset}
                          tabIndex={0}
                          onClick={() => { setSelectedFinding(finding); setSelectedNode(null); setEvidenceDetail(null); }}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              setSelectedFinding(finding);
                              setSelectedNode(null);
                              setEvidenceDetail(null);
                            }
                          }}
                          aria-label={`Open finding for ${finding.asset}`}
                        >
                          <td><strong>{finding.asset}</strong><small>{finding.source_system || 'Source not specified'}</small></td>
                          <td>{finding.asset_type}</td>
                          <td><StateBadge state={finding.finding_state} /></td>
                          <td className="finding-reason">{finding.reason}</td>
                          <td><strong>{formatDate(latestEvidenceTime(finding))}</strong><small>{finding.evidence.length} evidence {finding.evidence.length === 1 ? 'record' : 'records'}</small></td>
                        </tr>
                      ))}
                      {visibleFindings.length === 0 ? <tr><td colSpan={5} className="empty-table">No findings match this classification.</td></tr> : null}
                    </tbody>
                  </table>
                </div>
                <p className="table-note">Select a finding to inspect its evidence, provenance, and recommended action.</p>
              </section>

              <div className="lower-grid">
                <section className="section-block timeline-section" id="timeline">
                  <div className="section-heading">
                    <div><span className="section-index">04</span><h2>Evidence timeline</h2></div>
                    <span className="section-context">{visibleTimeline.length} records</span>
                  </div>
                  <div className="timeline-filters" role="group" aria-label="Filter evidence timeline">
                    {timelineCategories.map((category) => (
                      <button key={category} type="button" className={timelineFilter === category ? 'selected' : ''} aria-pressed={timelineFilter === category} onClick={() => setTimelineFilter(category)}>{category}</button>
                    ))}
                  </div>
                  <div className="timeline-list">
                    {visibleTimeline.map(({ evidence, finding }) => (
                      <button key={`${finding.asset}-${evidence.evidence_id}`} type="button" className="timeline-row" onClick={() => void openEvidence(evidence.evidence_id, finding)}>
                        <span className="timeline-timestamp">{formatDate(evidence.timestamp || finding.event_time)}</span>
                        <span className="timeline-event">
                          <strong>{evidence.source_record || finding.asset}</strong>
                          <span>{evidence.raw_excerpt || finding.reason}</span>
                          <small>{finding.source_system || finding.asset} · {evidence.source_type}</small>
                        </span>
                        <span className={`evidence-status status-${evidence.evidence_status}`}>{evidence.evidence_status}</span>
                      </button>
                    ))}
                    {visibleTimeline.length === 0 ? <div className="empty-inline">No evidence events match this filter.</div> : null}
                  </div>
                </section>

                <div className="right-rail">
                  <section className="section-block remediation-section" id="remediation">
                    <div className="section-heading">
                      <div><span className="section-index">05</span><h2>Verification action</h2></div>
                    </div>
                    <div className="recommendation">
                      <span className="minor-label">FIRST BREAK · {firstBreak?.asset || 'UNRESOLVED'}</span>
                      <p>{firstBreak?.recommended_action || 'Review available evidence and identify the next verification step.'}</p>
                      <div className="action-buttons">
                        <button type="button" className="secondary-button" onClick={() => setActionNotice('Verification tasks are not connected in this synthetic demo. No task was created.')}>Create verification task</button>
                        <button type="button" className="secondary-button" onClick={() => void investigate()}>Re-run investigation</button>
                        <button type="button" className="primary-button" onClick={() => void simulateRemediation()}>Simulate remediation</button>
                      </div>
                      {actionNotice ? <p className="action-notice" role="status">{actionNotice}</p> : null}
                      {remediationResult ? (
                        <div className="remediation-result">
                          <strong>Simulation result · {remediationResult.overall_investigation_state.replaceAll('_', ' ')}</strong>
                          <p>{remediationResult.remediation_summary || 'Simulation response received from the backend.'}</p>
                          <div className="compare-list">
                            {remediationResult.findings.map((finding) => (
                              <div key={finding.asset}><span>{finding.asset}</span><StateBadge state={finding.finding_state} /></div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </section>

                  <section className="section-block quality-section" id="evidence-quality">
                    <div className="section-heading">
                      <div><span className="section-index">06</span><h2>Evidence interpretation</h2></div>
                    </div>
                    <p className="quality-intro">Evidence status describes the source record, not the finding classification.</p>
                    <div className="quality-grid">
                      {(Object.entries(evidenceStatusHelp) as Array<[EvidenceStatus, string]>).map(([status, explanation]) => (
                        <div key={status} className="quality-item"><strong>{status}</strong><span>{explanation}</span></div>
                      ))}
                    </div>
                  </section>
                </div>
              </div>
              {error ? <div className="inline-error" role="alert">{error}</div> : null}
            </>
          )}
        </main>
      </div>

      {selectedFinding || selectedNode ? (
        <div className="drawer-scrim" onClick={() => { setSelectedFinding(null); setSelectedNode(null); setEvidenceDetail(null); }}>
          <aside
            className="evidence-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={selectedFinding ? `Finding evidence for ${selectedFinding.asset}` : `Lineage context for ${selectedNode?.label}`}
            onClick={(event) => event.stopPropagation()}
          >
            {selectedFinding ? <>
            <div className="drawer-header">
              <div><span className="minor-label">FINDING DETAIL</span><h2>{selectedFinding.asset}</h2></div>
              <button className="icon-button" type="button" aria-label="Close evidence drawer" onClick={() => { setSelectedFinding(null); setSelectedNode(null); setEvidenceDetail(null); }}>×</button>
            </div>
            <StateBadge state={selectedFinding.finding_state} />
            <div className="drawer-section">
              <p className="drawer-explanation">{selectedFinding.reason}</p>
              <dl className="drawer-facts">
                <div><dt>Asset type</dt><dd>{selectedFinding.asset_type}</dd></div>
                <div><dt>Person</dt><dd>{result?.customer_id || '—'}</dd></div>
                <div><dt>Purpose</dt><dd>{result?.purpose || '—'}</dd></div>
                <div><dt>Source</dt><dd>{selectedFinding.source_system || '—'}</dd></div>
                <div><dt>Latest event time</dt><dd>{formatDate(selectedFinding.event_time)}</dd></div>
                <div><dt>Observed time</dt><dd>{formatDate(selectedFinding.observed_time)}</dd></div>
              </dl>
            </div>
            <div className="drawer-section">
              <div className="drawer-section-heading"><h3>Evidence records</h3><span>{selectedFinding.evidence.length}</span></div>
              {selectedFinding.evidence.length ? (
                <ul className="drawer-evidence-list">
                  {selectedFinding.evidence.map((item) => (
                    <li key={item.evidence_id}>
                      <button type="button" className="evidence-select" onClick={() => void openEvidence(item.evidence_id, selectedFinding)}>
                        <span><strong>{item.evidence_id}</strong><small>{item.source_record} · {formatDate(item.timestamp)}</small></span>
                        <span className={`evidence-status status-${item.evidence_status}`}>{item.evidence_status}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <p className="muted-copy">No evidence records are associated with this finding.</p>}
            </div>
            <div className="drawer-section">
              <div className="provenance">
                <span>Source</span><i aria-hidden="true">→</i><span>Ingestion event</span><i aria-hidden="true">→</i><span>Finding</span>
              </div>
              <p className="muted-copy">Evidence is associated with this finding through persisted event records. Static lineage is shown separately from runtime evidence.</p>
              <div className="drawer-actions">
                <button type="button" className="secondary-button" onClick={() => { setSelectedFinding(null); scrollTo('timeline'); }}>View related events</button>
                <button type="button" className="secondary-button" onClick={() => { setSelectedFinding(null); scrollTo('processing-path'); }}>View lineage</button>
              </div>
            </div>
            {selectedFinding.recommended_action ? (
              <div className="drawer-section"><span className="minor-label">RECOMMENDED ACTION</span><p className="drawer-explanation">{selectedFinding.recommended_action}</p></div>
            ) : null}
            {evidenceLoading ? <div className="evidence-loading">Loading persisted evidence…</div> : null}
            {evidenceDetail ? (
              <section className="selected-evidence" aria-label="Selected evidence record">
                <div className="drawer-section-heading"><h3>{evidenceDetail.evidence_id}</h3><span className={`evidence-status status-${evidenceDetail.evidence_status}`}>{evidenceDetail.evidence_status}</span></div>
                <dl className="drawer-facts">
                  <div><dt>Source</dt><dd>{evidenceDetail.source_system || evidenceDetail.source_type || '—'}</dd></div>
                  <div><dt>Source record</dt><dd>{evidenceDetail.source_record || '—'}</dd></div>
                  <div><dt>Event time</dt><dd>{formatDate(evidenceDetail.timestamp)}</dd></div>
                  <div><dt>Observed time</dt><dd>{formatDate(evidenceDetail.observed_time)}</dd></div>
                  <div><dt>Ingested time</dt><dd>{formatDate(evidenceDetail.ingested_at)}</dd></div>
                  <div><dt>Integrity</dt><dd>{evidenceDetail.integrity_hash ? `SHA-256 · ${evidenceDetail.integrity_hash}` : 'Not available'}</dd></div>
                </dl>
                <div className="excerpt-box"><span className="minor-label">SOURCE EXCERPT</span><p>{evidenceDetail.raw_excerpt || 'No source excerpt available.'}</p></div>
                <p className="muted-copy">{evidenceStatusHelp[evidenceDetail.evidence_status]}</p>
                {evidenceDetail.source_url
                  ? <a className="source-link" href={evidenceDetail.source_url} target="_blank" rel="noreferrer">Open source record ↗</a>
                  : <span className="source-unavailable">Source record link not available</span>}
              </section>
            ) : null}
            </> : selectedNode ? <>
              <div className="drawer-header">
                <div><span className="minor-label">LINEAGE NODE CONTEXT</span><h2>{selectedNode.label}</h2></div>
                <button className="icon-button" type="button" aria-label="Close lineage context" onClick={() => setSelectedNode(null)}>×</button>
              </div>
              {selectedNode.state ? <StateBadge state={selectedNode.state} /> : <span className="unavailable-state">Classification unavailable</span>}
              <div className="drawer-section">
                <dl className="drawer-facts">
                  <div><dt>Node type</dt><dd>{selectedNode.kind}</dd></div>
                  <div><dt>Last relevant time</dt><dd>{formatDate(result?.withdrawal_timestamp || selectedNode.timestamp)}</dd></div>
                  <div><dt>Evidence count</dt><dd>0 directly associated findings</dd></div>
                </dl>
                <p className="muted-copy">This lineage node is returned by the graph endpoint but is not represented as a finding in the investigation response. No runtime evidence is attached to this node.</p>
              </div>
              <div className="drawer-section">
                <p className="muted-copy">Static lineage describes system relationships; it is not runtime evidence of processing.</p>
                <button type="button" className="secondary-button" onClick={() => setSelectedNode(null)}>Return to lineage</button>
              </div>
            </> : null}
          </aside>
        </div>
      ) : null}
      {loading ? <div className="loading-bar" role="status">Loading investigation evidence…</div> : null}
    </div>
  );
}
