import React, { useState, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const api = async (path, token, body, method = 'GET') => {
  const r = await fetch(path, {
    method: body ? 'POST' : method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${r.status} on ${path}`)
  return r.json()
}
const patch = async (path, token, body) => {
  const r = await fetch(path, { method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`${r.status} on ${path}`)
  return r.json()
}
const upload = async (path, token, file) => {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
  if (!r.ok) throw new Error(`${r.status} on ${path}`)
  return r.json()
}
const badgeClass = (stage) => stage === 'Converted' ? 'teal' : stage === 'Qualified' ? 'gold' : stage === 'Consultation' ? 'navy' : stage === 'Lost' ? 'red' : 'slate'

/* Inline stroke icons (no icon library) */
const I = ({ d, children }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children || <path d={d} />}
  </svg>
)
const ICONS = {
  dashboard: <I><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></I>,
  leads: <I><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5" /><path d="M18 5v6M15 8h6" /></I>,
  clients: <I><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5" /><circle cx="17" cy="9" r="2.6" /><path d="M16.5 15.4c2.6.3 4.4 1.9 5 4.6" /></I>,
  cases: <I><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18" /></I>,
  messages: <I><path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5z" /></I>,
  calendar: <I><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></I>,
  documents: <I><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M9 13h6M9 17h6" /></I>,
  billing: <I><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M3 10h18M7 15h4" /></I>,
  reports: <I><path d="M4 20V10M10 20V4M16 20v-8M22 20H2" /></I>,
  retainers: <I><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></I>,
  forms: <I><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4a3 3 0 0 1 6 0M9 11h6M9 15h4" /></I>,
  chasing: <I><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></I>,
  precheck: <I><circle cx="12" cy="12" r="9" /><path d="M8.5 12.5l2.5 2.5 5-5.5" /></I>,
  comms: <I><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M2 7l10 6L22 7" /></I>,
  settings: <I><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.4a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.23.6.86 1 1.55 1H21a2 2 0 1 1 0 4h-.09c-.69 0-1.32.4-1.51 1z" /></I>,
  menu: <I><path d="M4 6h16M4 12h16M4 18h16" /></I>,
  collapse: <I><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5" /></I>,
}
const NAV = [
  ['dashboard', 'Dashboard', 'dashboard'], ['leads', 'Leads', 'leads'], ['clients', 'Clients', 'clients'],
  ['cases', 'Cases', 'cases'], ['messages', 'Messages', 'messages'], ['calendar', 'Calendar', 'calendar'],
  ['documents', 'Documents', 'documents'], ['billing', 'Billing', 'billing'], ['reports', 'Reports', 'reports'],
  ['retainers', 'Retainers', 'retainers'], ['forms', 'IRCC Forms', 'forms'], ['chasing', 'Chasing', 'chasing'],
  ['precheck', 'Pre-check', 'precheck'], ['comms', 'Comms Settings', 'comms'], ['settings', 'Settings', 'settings'],
]
const PAGE_TITLE = Object.fromEntries(NAV.map(([k, label]) => [k, label]))

function SignIn({ onDone, onPortal }) {
  const [email, setEmail] = useState('admin@demo.example')
  const [code, setCode] = useState('')
  const [step, setStep] = useState(1)
  const [msg, setMsg] = useState('')
  const request = async () => {
    const res = await api('/api/auth/request-otp', null, { email })
    setMsg(res.dev_code ? `Development mode — your code is ${res.dev_code} (no message sent).` : res.detail)
    setStep(2)
  }
  const verify = async () => {
    const res = await api('/api/auth/verify-otp', null, { email, code })
    localStorage.setItem('icrm_token', res.token)
    onDone(res.token)
  }
  return (<div className="login-wrap"><div className="card login-card">
    <div className="login-brand"><span className="brand-mark">IC</span><h1>Immigration CRM</h1></div>
    <h2>Sign in to your firm</h2>
    {step === 1 ? (<>
      <div className="field"><label htmlFor="si-email">Work email address</label>
        <input id="si-email" type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} /></div>
      <button className="btn btn-block" onClick={request}>Send sign-in code</button>
    </>) : (<>
      <p className="callout">{msg}</p>
      <div className="field"><label htmlFor="si-code">Sign-in code</label>
        <input id="si-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} /></div>
      <button className="btn btn-block" onClick={verify}>Sign in</button>
    </>)}
    <div className="login-foot"><p><button className="link-btn" onClick={onPortal}>I am a client — open the client portal</button></p></div>
  </div></div>)
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('icrm_token'))
  const [portalToken, setPortalToken] = useState(localStorage.getItem('icrm_portal_token'))
  const [portal, setPortal] = useState(false)
  const [page, setPage] = useState('dashboard')
  const [me, setMe] = useState(null)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => {
    if (!token) return
    api('/api/me', token).then(setMe).catch(() => { localStorage.removeItem('icrm_token'); setToken(null) })
  }, [token])
  useEffect(() => {
    if (!token) return
    const path = page === 'dashboard' ? '/api/dashboard' : page === 'leads' ? '/api/leads' : page === 'clients' ? '/api/clients' : page === 'cases' ? '/api/cases' : page === 'messages' ? '/api/cases' : page === 'calendar' ? '/api/consultations' : page === 'comms' ? '/api/settings/communications' : page === 'documents' ? '/api/review-queue' : page === 'billing' ? '/api/invoices' : page === 'reports' ? '/api/reports/summary' : page === 'retainers' || page === 'forms' || page === 'chasing' || page === 'precheck' ? '/api/cases' : '/api/settings'
    api(path, token).then(setData).catch(e => setErr(String(e)))
  }, [token, page])
  const go = (p) => { setPage(p); setData(null); setErr(''); setNavOpen(false) }
  if (portalToken) return <PortalApp token={portalToken} onSignOut={() => { localStorage.removeItem('icrm_portal_token'); setPortalToken(null); setPortal(false) }} />
  if (portal) return <PortalSignIn onDone={(t) => { localStorage.setItem('icrm_portal_token', t); setPortalToken(t) }} onBack={() => setPortal(false)} />
  if (!token) return <SignIn onDone={setToken} onPortal={() => setPortal(true)} />
  const initials = me && me.full_name ? me.full_name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() : ''
  return (<div className={`shell${collapsed ? ' collapsed' : ''}`}>
    {navOpen && <button className="scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} />}
    <aside className={`sidebar${navOpen ? ' open' : ''}`}>
      <div className="brand"><span className="brand-mark">IC</span><span>IMMIGRATION CRM</span></div>
      <nav>
        {NAV.map(([p, label, icon]) =>
          <button key={p} className={p === page ? 'active' : ''} onClick={() => go(p)}>{ICONS[icon]}<span className="nav-label">{label}</span></button>)}
      </nav>
      <div className="tenant">
        <div className="who"><span className="avatar">{initials}</span><span className="who-text" title={me ? `${me.tenant} — ${me.full_name} (${me.role})` : ''}><b>{me ? me.tenant : ''}</b>{me ? `${me.full_name} (${me.role})` : ''}</span></div>
        <button className="logout" onClick={() => { localStorage.removeItem('icrm_token'); setToken(null) }}>Sign out</button>
      </div>
    </aside>
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <header className="topbar">
        <button className="icon-btn menu-btn" aria-label="Open menu" onClick={() => setNavOpen(true)}>{ICONS.menu}</button>
        <button className="icon-btn collapse-btn" aria-label="Collapse sidebar" onClick={() => setCollapsed(!collapsed)}>{ICONS.collapse}</button>
        <span className="page-title">{PAGE_TITLE[page]}</span>
        {me && <span className="user-chip"><span className="avatar">{initials}</span>{me.full_name}</span>}
      </header>
      <main className="main">
        {err && <p className="error">{err}</p>}
        {!data && !err && <p className="muted">Loading…</p>}
        {page === 'dashboard' && data && (<div>
          <div className="page-head"><h2>Firm dashboard</h2><p className="page-sub">Overview of your firm today</p></div>
          <div className="stats">
            <div className="stat"><span className="stat-ic">{ICONS.cases}</span><b>{data.active_cases}</b><span>Active cases</span></div>
            <div className="stat"><span className="stat-ic">{ICONS.leads}</span><b>{data.total_leads}</b><span>Total leads</span></div>
            <div className="stat"><span className="stat-ic">{ICONS.chasing}</span><b>{data.upcoming_follow_ups.length}</b><span>Upcoming follow-ups</span></div>
          </div>
          <div className="grid">
            <div className="card"><h3>Leads by stage</h3>{Object.entries(data.leads_by_stage).map(([s, n]) => <div className="stage-row" key={s}><span className="stage-name">{s}</span><span className="stage-count">{n}</span><span className="share-bar"><i style={{ width: `${data.total_leads ? (n / data.total_leads) * 100 : 0}%` }} /></span></div>)}</div>
            <div className="card"><h3>Cases by stream</h3><ul className="kv-list">{Object.entries(data.cases_by_stream).map(([s, n]) => <li key={s}><span>{s}</span><span className="kv-val">{n}</span></li>)}</ul></div>
          </div>
          <div className="stack">
            <div className="card"><h3>Upcoming follow-ups</h3>{data.upcoming_follow_ups.length === 0 ? <p className="muted">None scheduled.</p> : <ul className="kv-list">{data.upcoming_follow_ups.map((u, i) => <li key={i}><span>{u.name} ({u.type})</span><span className="kv-val">{u.date}</span></li>)}</ul>}</div>
            <div className="card"><h3>Action items (failed sends, reminders, syncs)</h3>{(data.action_items || []).length === 0 ? <p className="muted">Nothing needs attention.</p> : <ul>{(data.action_items || []).map(a => <li key={a.id}>{a.title} — {a.detail}</li>)}</ul>}</div>
            <div className="card"><h3>Upcoming deadlines</h3>{(data.upcoming_deadlines || []).length === 0 ? <p className="muted">No deadlines coming up.</p> : <ul className="kv-list">{(data.upcoming_deadlines || []).map(d => <li key={d.id}><span>{d.title} (case #{d.case_id})</span><span className="kv-val">{d.due_date}</span></li>)}</ul>}</div>
            <div className="card"><h3>Upcoming consultations</h3>{(data.upcoming_consultations || []).length === 0 ? <p className="muted">None scheduled.</p> : <ul className="kv-list">{(data.upcoming_consultations || []).map(c => <li key={c.id}><span>{c.kind} ({c.status})</span><span className="kv-val">{c.starts_at}</span></li>)}</ul>}</div>
          </div>
        </div>)}
        {page === 'documents' && data && (<DocumentsPage token={token} />)}
        {page === 'billing' && data && (<BillingPage token={token} invoices={data} refresh={() => api('/api/invoices', token).then(setData)} />)}
        {page === 'reports' && data && (<ReportsPage token={token} summary={data} />)}
        {page === 'messages' && data && (<MessagesPage token={token} cases={data} />)}
        {page === 'retainers' && data && (<RetainersPage token={token} cases={data} />)}
        {page === 'forms' && data && (<FormsPage token={token} cases={data} />)}
        {page === 'chasing' && data && (<ChasingPage token={token} cases={data} />)}
        {page === 'precheck' && data && (<PrecheckPage token={token} />)}
        {page === 'calendar' && data && (<CalendarPage token={token} consultations={data} />)}
        {page === 'comms' && data && (<CommsPage token={token} comms={data} />)}
        {page === 'leads' && data && (<Leads token={token} leads={data} refresh={() => api('/api/leads', token).then(setData)} />)}
        {page === 'clients' && data && (<div>
          <div className="page-head"><h2>Clients</h2><p className="page-sub">{data.length} client{data.length === 1 ? '' : 's'}</p></div>
          <ul className="list">{data.map(c => <li className="list-item" key={c.id}><span className="avatar">{c.full_name ? c.full_name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() : ''}</span><span className="grow"><b>{c.full_name}</b><br /><span className="meta">{c.email} · {c.phone}</span></span></li>)}</ul>
        </div>)}
        {page === 'cases' && data && (<div>
          <div className="page-head"><h2>Cases</h2><p className="page-sub">{data.length} case{data.length === 1 ? '' : 's'}</p></div>
          <ul className="list">{data.map(c => <li className="list-item" key={c.id}><span className="grow"><b>Case #{c.id} — {c.stream}</b><br /><span className="meta">File {c.ircc_file_number || '—'}</span></span><span className={`badge ${badgeClass(c.stage)}`}>{c.stage}</span></li>)}</ul>
        </div>)}
        {page === 'settings' && data && (<div>
          <div className="page-head"><h2>Settings</h2><p className="page-sub">Firm, branches and team</p></div>
          <div className="stack">
            <div className="card"><h3>Firm</h3><p>{data.firm}</p></div>
            <div className="card"><h3>Branches</h3><ul className="list">{data.branches.map(b => <li className="list-item" key={b.id}><span className="grow"><b>{b.name}</b><br /><span className="meta">{b.city}</span></span></li>)}</ul></div>
            <div className="card"><h3>Team</h3><ul className="list">{data.team.map(u => <li className="list-item" key={u.id}><span className="grow"><b>{u.full_name}</b><br /><span className="meta">{u.role} · {u.email}</span></span></li>)}</ul></div>
            <SubscriptionBlock token={token} />
          </div>
        </div>)}
      </main>
    </div>
  </div>)
}

function Leads({ token, leads, refresh }) {
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [stream, setStream] = useState('Express Entry')
  const [source, setSource] = useState('')
  const [referral, setReferral] = useState('')
  const [notes, setNotes] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [detailId, setDetailId] = useState(null)
  const clearForm = () => { setName(''); setPhone(''); setEmail(''); setStream('Express Entry'); setSource(''); setReferral(''); setNotes(''); setFollowUp('') }
  const add = async () => {
    if (!name.trim()) return
    const fullNotes = [referral.trim() ? `Referral: ${referral.trim()}` : '', notes.trim()].filter(Boolean).join('\n')
    await api('/api/leads', token, { full_name: name.trim(), phone, email, source, stream_of_interest: stream, notes: fullNotes, next_follow_up: followUp || null })
    clearForm(); setShowForm(false); refresh()
  }
  const move = async (id, stage) => { await patch(`/api/leads/${id}`, token, { stage }); refresh() }
  const convert = async (id) => { await api(`/api/leads/${id}/convert`, token, {}, 'POST'); refresh() }
  return (<div>
    <div className="page-head"><h2>Leads pipeline</h2><p className="page-sub">{leads.length} lead{leads.length === 1 ? '' : 's'}</p></div>
    {!showForm && <div className="toolbar"><button className="btn" onClick={() => setShowForm(true)}>Add lead</button></div>}
    {showForm && <div className="card add-form"><h3>Add lead</h3>
      <div className="form-grid">
        <div className="field"><label htmlFor="ld-name">Full name</label><input id="ld-name" value={name} onChange={e => setName(e.target.value)} /></div>
        <div className="field"><label htmlFor="ld-phone">Phone</label><input id="ld-phone" type="tel" value={phone} onChange={e => setPhone(e.target.value)} /></div>
        <div className="field"><label htmlFor="ld-email">Email</label><input id="ld-email" type="email" value={email} onChange={e => setEmail(e.target.value)} /></div>
        <div className="field"><label htmlFor="ld-stream">Stream</label><select id="ld-stream" value={stream} onChange={e => setStream(e.target.value)}>{['Express Entry', 'PNP', 'LMIA', 'Study', 'Work', 'Family Sponsorship'].map(s => <option key={s}>{s}</option>)}</select></div>
        <div className="field"><label htmlFor="ld-source">Source</label><select id="ld-source" value={source} onChange={e => setSource(e.target.value)}>{['', 'Website', 'WhatsApp', 'Facebook', 'Instagram', 'Referral', 'Walk-in', 'Other'].map(s => <option key={s} value={s}>{s || '—'}</option>)}</select></div>
        <div className="field"><label htmlFor="ld-referral">Referral details</label><input id="ld-referral" value={referral} onChange={e => setReferral(e.target.value)} /></div>
        <div className="field"><label htmlFor="ld-notes">Notes</label><textarea id="ld-notes" value={notes} onChange={e => setNotes(e.target.value)} /></div>
        <div className="field"><label htmlFor="ld-followup">Next follow-up</label><input id="ld-followup" type="date" value={followUp} onChange={e => setFollowUp(e.target.value)} /></div>
      </div>
      <div className="row-actions"><button className="btn" onClick={add}>Save lead</button>
      <button onClick={() => { clearForm(); setShowForm(false) }}>Cancel</button></div></div>}
    <div className="table-wrap"><table className="data"><thead><tr><th>Name</th><th>Stream</th><th>Stage</th><th>Source</th><th>Actions</th></tr></thead>
    <tbody>{leads.map(l => (<React.Fragment key={l.id}><tr>
      <td data-label="Name"><b>{l.full_name}</b></td>
      <td data-label="Stream">{l.stream_of_interest}</td>
      <td data-label="Stage"><span className={`badge ${badgeClass(l.stage)}`}>{l.stage}</span></td>
      <td data-label="Source">{l.source}</td>
      <td data-label="Actions"><div className="row-actions">
        <button onClick={() => setDetailId(detailId === l.id ? null : l.id)}>Details</button>
        <button onClick={() => move(l.id, 'Contacted')}>Contacted</button>
        <button onClick={() => move(l.id, 'Qualified')}>Qualified</button>
        <button onClick={() => move(l.id, 'Consultation')}>Consultation</button>
        {l.stage !== 'Converted' && l.stage !== 'Lost' && <button onClick={() => convert(l.id)}>Convert to client + case</button>}
        <button onClick={() => move(l.id, 'Lost')}>Lost</button>
      </div></td></tr>
      {detailId === l.id && <tr><td colSpan={5} className="detail-cell"><LeadDetail token={token} lead={l} /></td></tr>}
    </React.Fragment>))}</tbody></table></div>
  </div>)
}

function LeadDetail({ token, lead }) {
  const [msgs, setMsgs] = useState([])
  const [consultantId, setConsultantId] = useState('')
  const [starts, setStarts] = useState('')
  const [ends, setEnds] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => { api(`/api/leads/${lead.id}/messages`, token).then(setMsgs).catch(() => {}) }, [lead.id])
  const book = async () => {
    try {
      const c = await api('/api/consultations', token, { consultant_id: Number(consultantId), lead_id: lead.id, starts_at: starts, ends_at: ends })
      setNote(`Booked consultation #${c.id} for this lead (status ${c.status}). No retyping — linked to the lead.`)
    } catch (e) { setNote(String(e)) }
  }
  return (<div className="lead-detail">
    <p className="meta">Contact: {lead.email} {lead.phone} · Source: {lead.source} · Notes: {lead.notes || '—'}</p>
    <h4>Inline booking (Feature 13)</h4>
    <div className="form-row">
      <div className="field"><label htmlFor="lbd-cid">Consultant id</label><input id="lbd-cid" inputMode="numeric" value={consultantId} onChange={e => setConsultantId(e.target.value)} /></div>
      <div className="field grow"><label htmlFor="lbd-start">Start</label><input id="lbd-start" placeholder="2026-11-05T10:00:00" value={starts} onChange={e => setStarts(e.target.value)} /></div>
      <div className="field grow"><label htmlFor="lbd-end">End</label><input id="lbd-end" placeholder="2026-11-05T10:30:00" value={ends} onChange={e => setEnds(e.target.value)} /></div>
      <button onClick={book}>Book for this lead</button>
    </div>
    {note && <p className="note">{note}</p>}
    <h4>Messages for this lead</h4>
    {msgs.length === 0 ? <p className="muted">No messages yet.</p> : <ul className="list">{msgs.map(m => <li className="list-item" key={m.id}><span className="grow">[{m.channel}] {m.status} — {m.body}</span></li>)}</ul>}
  </div>)
}

function MessagesPage({ token, cases }) {
  const [caseId, setCaseId] = useState(cases[0] ? cases[0].id : '')
  const [msgs, setMsgs] = useState([])
  const [drafts, setDrafts] = useState([])
  const [channel, setChannel] = useState('sms')
  const [body, setBody] = useState('')
  const [note, setNote] = useState('')
  const load = async (id) => {
    if (!id) return
    setMsgs(await api(`/api/cases/${id}/messages`, token))
    setDrafts(await api(`/api/cases/${id}/drafts`, token))
  }
  useEffect(() => { load(caseId) }, [caseId])
  const send = async () => {
    if (!body.trim()) return
    const m = await api(`/api/cases/${caseId}/messages`, token, { channel, body })
    setNote(`Recorded as ${m.status} (log mode = would send, delivered to nobody).`)
    setBody(''); load(caseId)
  }
  const draft = async (kind) => {
    const d = await api(`/api/cases/${caseId}/drafts`, token, { kind, channel })
    setNote(`Draft #${d.id} ready for staff review — nothing sent.`)
    load(caseId)
  }
  const approve = async (id) => {
    const r = await api(`/api/drafts/${id}/approve`, token, {}, 'POST')
    setNote(`Draft approved — sent as staff message, status ${r.sent_message.status}.`)
    load(caseId)
  }
  return (<div>
    <div className="page-head"><h2>Case messages + AI drafts</h2><p className="page-sub">SMS and email, with AI drafts behind a human gate</p></div>
    <div className="toolbar"><div className="field"><label htmlFor="msg-case">Case</label><select id="msg-case" value={caseId} onChange={e => setCaseId(e.target.value)}>{cases.map(c => <option key={c.id} value={c.id}>Case #{c.id} — {c.stream} ({c.stage})</option>)}</select></div></div>
    {note && <p className="note">{note}</p>}
    <div className="card" style={{ marginBottom: 16 }}>
      <h3>Compose</h3>
      <div className="form-row">
        <div className="field"><label htmlFor="msg-channel">Channel</label><select id="msg-channel" value={channel} onChange={e => setChannel(e.target.value)}><option value="sms">SMS</option><option value="email">Email</option></select></div>
        <div className="field grow"><label htmlFor="msg-body">Message text</label><input id="msg-body" placeholder="Message text" value={body} onChange={e => setBody(e.target.value)} /></div>
        <button className="btn" onClick={send}>Send (staff)</button>
      </div>
    </div>
    <div className="card" style={{ marginBottom: 16 }}><h3>Message log (chronological, SMS + email)</h3>
      {msgs.length === 0 ? <p className="muted">No messages yet.</p> : <ul className="list">{msgs.map(m => <li className="list-item" key={m.id}><span className="grow">[{m.channel}] {m.status} — {m.body} <span className="meta">({m.source}{m.draft_id ? `, draft #${m.draft_id}` : ''})</span></span></li>)}</ul>}
    </div>
    <div className="card"><h3>AI drafts (human gate — drafts never send themselves)</h3>
      <div className="row-actions" style={{ marginBottom: 12 }}>
        <button onClick={() => draft('document_request')}>Draft document request</button>
        <button onClick={() => draft('deadline_summary')}>Draft deadline summary</button>
      </div>
      {drafts.length === 0 ? <p className="muted">No drafts yet.</p> : <ul className="list">{drafts.map(d => <li className="list-item" key={d.id}><span className="grow">{d.kind} ({d.channel}) — {d.status}: {d.body}</span>
        {d.status === 'draft' && <button className="btn" onClick={() => approve(d.id)}>Approve + send</button>}</li>)}</ul>}
    </div>
  </div>)
}

function CalendarPage({ token, consultations }) {
  const [consultantId, setConsultantId] = useState('')
  const [starts, setStarts] = useState('')
  const [ends, setEnds] = useState('')
  const [week, setWeek] = useState(null)
  const [note, setNote] = useState('')
  const book = async () => {
    try {
      const c = await api('/api/consultations', token, { consultant_id: Number(consultantId), starts_at: starts, ends_at: ends })
      setNote(`Booked: consultation #${c.id}, status ${c.status}, sync ${c.sync_status}.`)
    } catch (e) { setNote(String(e)) }
  }
  const loadWeek = async () => {
    const w = await api(`/api/calendar/week?consultant_id=${consultantId}&from_date=${starts}&to_date=${ends}`, token)
    setWeek(w)
  }
  return (<div>
    <div className="page-head"><h2>Calendar + consultations</h2><p className="page-sub">Week view, bookings and Google sync</p></div>
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="form-row">
        <div className="field"><label htmlFor="cal-cid">Consultant id</label><input id="cal-cid" inputMode="numeric" value={consultantId} onChange={e => setConsultantId(e.target.value)} /></div>
        <div className="field grow"><label htmlFor="cal-start">Start</label><input id="cal-start" placeholder="2026-11-05T10:00:00" value={starts} onChange={e => setStarts(e.target.value)} /></div>
        <div className="field grow"><label htmlFor="cal-end">End</label><input id="cal-end" placeholder="2026-11-05T10:30:00" value={ends} onChange={e => setEnds(e.target.value)} /></div>
      </div>
      <div className="row-actions" style={{ marginTop: 14 }}>
        <button className="btn" onClick={book}>Book consultation</button>
        <button onClick={loadWeek}>Load week view</button>
      </div>
      {note && <p className="note" style={{ marginTop: 14 }}>{note}</p>}
    </div>
    <div className="card" style={{ marginBottom: 16 }}><h3>Consultations</h3>
      {consultations.length === 0 ? <p className="muted">None scheduled.</p> : <ul className="list">{consultations.map(c => <li className="list-item" key={c.id}><span className="grow"><b>#{c.id} — {c.kind}</b><br /><span className="meta">{c.starts_at} ({c.status}, {c.source}, sync {c.sync_status})</span></span></li>)}</ul>}
    </div>
    {week && (<div className="card"><h3>Week view</h3>
      <p>Bookings: {week.consultations.length} · Blocked (Google) slots: {week.blocked_slots.length} · Deadlines: {week.deadlines.length}</p>
      <ul className="list">
        {week.blocked_slots.map(b => <li className="list-item" key={b.id}><span className="grow"><span className="badge red">Blocked</span> {b.starts_at}–{b.ends_at} ({b.title})</span></li>)}
        {week.deadlines.map(d => <li className="list-item" key={d.id}><span className="grow"><span className="badge gold">Deadline</span> {d.due_date} — {d.title}</span></li>)}
      </ul></div>)}
  </div>)
}

function CommsPage({ token, comms }) {
  const [s, setS] = useState(comms.settings)
  const [note, setNote] = useState('')
  const save = async () => {
    const r = await patch('/api/settings/communications', token, { sms_mode: s.sms_mode, sms_sender: s.sms_sender, email_mode: s.email_mode, email_sender: s.email_sender, opt_out_wording: s.opt_out_wording })
    setS(r.settings); setNote('Settings saved. Live sending stays gated on sender verification + test receipt.')
  }
  const gate = async (action, channel) => {
    const r = await api(`/api/settings/communications/${action}`, token, { channel }, 'POST')
    setS(r.settings); setNote(`${action} recorded for ${channel}.`)
  }
  return (<div>
    <div className="page-head"><h2>Communications settings</h2><p className="page-sub">Firm admin — SMS and email sending controls</p></div>
    {note && <p className="note">{note}</p>}
    <div className="grid">
      <div className="card"><h3>SMS</h3>
        <div className="form-grid">
          <div className="field"><label htmlFor="cm-sms-mode">SMS mode</label><select id="cm-sms-mode" value={s.sms_mode} onChange={e => setS({ ...s, sms_mode: e.target.value })}><option value="log">log (default — would send only)</option><option value="live">live</option></select></div>
          <div className="field"><label htmlFor="cm-sms-sender">Sender</label><input id="cm-sms-sender" value={s.sms_sender} onChange={e => setS({ ...s, sms_sender: e.target.value })} /></div>
        </div>
        <p className="meta">Verified: {String(s.sms_sender_verified)} · Test received: {String(s.sms_test_received)}</p>
      </div>
      <div className="card"><h3>Email</h3>
        <div className="form-grid">
          <div className="field"><label htmlFor="cm-email-mode">Email mode</label><select id="cm-email-mode" value={s.email_mode} onChange={e => setS({ ...s, email_mode: e.target.value })}><option value="log">log (default)</option><option value="live">live</option></select></div>
          <div className="field"><label htmlFor="cm-email-sender">Sender</label><input id="cm-email-sender" value={s.email_sender} onChange={e => setS({ ...s, email_sender: e.target.value })} /></div>
        </div>
        <p className="meta">Verified: {String(s.email_sender_verified)} · Test received: {String(s.email_test_received)}</p>
      </div>
    </div>
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="field"><label htmlFor="cm-optout">Opt-out wording</label><input id="cm-optout" value={s.opt_out_wording} onChange={e => setS({ ...s, opt_out_wording: e.target.value })} /></div>
      <div className="row-actions">
        <button className="btn" onClick={save}>Save settings</button>
        <button onClick={() => gate('verify-sender', 'sms')}>Verify SMS sender</button>
        <button onClick={() => gate('verify-sender', 'email')}>Verify email sender</button>
        <button onClick={() => gate('confirm-test-received', 'sms')}>Confirm SMS test received</button>
        <button onClick={() => gate('confirm-test-received', 'email')}>Confirm email test received</button>
      </div>
    </div>
    <div className="card"><h3>Templates (firm-editable)</h3>
      <ul className="list">{comms.templates.map(t => <li className="list-item" key={t.id}><span className="grow"><b>{t.key}</b> <span className="meta">({t.channel})</span><br />{t.subject ? t.subject + ' — ' : ''}{t.body}</span></li>)}</ul>
      <p className="note">Live sending requires sender verification AND a received test message, per channel. Log mode is the default and never delivers.</p>
    </div>
  </div>)
}

function Suggestions({ suggestions, token, refresh }) {
  if (!suggestions || !suggestions.length) return null
  return (<div className="suggest-box">
    <b>AI suggestions (panel — nothing is saved until staff approve)</b>
    <ul>{suggestions.map(s => <li key={s.id}>
      [{s.kind}] {s.proposed_field}: {s.proposed_value}
      {s.source_excerpt ? ` — “${s.source_excerpt}”` : ''} ({s.status})
      {s.status === 'Pending' && (<span className="row-actions" style={{ display: 'inline-flex', marginLeft: 8 }}>
        <button onClick={async () => { await api(`/api/suggestions/${s.id}/approve`, token, {}); refresh() }}>Approve</button>
        <button onClick={async () => { await api(`/api/suggestions/${s.id}/reject`, token, {}); refresh() }}>Dismiss</button>
      </span>)}
    </li>)}</ul>
  </div>)
}

function DocumentsPage({ token }) {
  const [queue, setQueue] = useState([])
  const [expiring, setExpiring] = useState([])
  const [caseId, setCaseId] = useState('')
  const [checklist, setChecklist] = useState(null)
  const [reason, setReason] = useState({})
  const [file, setFile] = useState({})
  const [note, setNote] = useState('')
  const refresh = async () => {
    setQueue(await api('/api/review-queue', token))
    setExpiring(await api('/api/documents/expiring', token))
    if (caseId) setChecklist(await api(`/api/cases/${caseId}/checklist`, token))
  }
  useEffect(() => { refresh().catch(e => setNote(String(e))) }, [])
  const loadChecklist = async () => setChecklist(await api(`/api/cases/${caseId}/checklist`, token))
  const initChecklist = async () => setChecklist(await api(`/api/cases/${caseId}/checklist/init`, token, {}))
  const act = async (path, body) => { await api(path, token, body || {}); setNote('Done.'); refresh() }
  const packet = async () => {
    const r = await fetch(`/api/cases/${caseId}/packet`, { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) throw new Error(`${r.status} on packet`)
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `case-${caseId}-packet.zip`; a.click()
  }
  const itemRow = (it) => (<div className="doc-card" key={it.id}>
    <div className="doc-head"><b>{it.document_name}</b><span className="meta">({it.person})</span><span className={`badge ${it.status === 'Approved' ? 'teal' : it.status === 'Rejected' ? 'red' : 'gold'}`}>{it.status}</span></div>
    <p className="doc-meta">
      {it.expiry_date ? `Expires ${it.expiry_date} · ` : ''}
      {it.rejection_reason ? `Rejected: ${it.rejection_reason} · ` : ''}
      {it.latest_version ? `v${it.latest_version.version_no} ${it.latest_version.original_filename} (${it.latest_version.review_decision})` : 'No version uploaded yet'}
    </p>
    <Suggestions suggestions={it.latest_version ? it.latest_version.suggestions : []} token={token} refresh={refresh} />
    <div className="doc-actions">
      <button onClick={() => act(`/api/checklist-items/${it.id}/request`)}>Request</button>
      <button onClick={() => act(`/api/checklist-items/${it.id}/start-review`)}>Start review</button>
      <button onClick={() => act(`/api/checklist-items/${it.id}/approve`)}>Approve</button>
      <div className="field"><label htmlFor={`rej-${it.id}`}>Rejection reason</label><input id={`rej-${it.id}`} placeholder="Rejection reason" value={reason[it.id] || ''} onChange={e => setReason({ ...reason, [it.id]: e.target.value })} /></div>
      <button onClick={() => act(`/api/checklist-items/${it.id}/reject`, { reason: reason[it.id] || '' })}>Reject with reason</button>
      <div className="field"><label htmlFor={`up-${it.id}`}>Upload (staff)</label><input id={`up-${it.id}`} type="file" onChange={e => setFile({ ...file, [it.id]: e.target.files[0] })} /></div>
      <button onClick={async () => { if (file[it.id]) { await upload(`/api/checklist-items/${it.id}/upload`, token, file[it.id]); setNote('Uploaded.'); refresh() } }}>Upload (staff)</button>
    </div>
  </div>)
  return (<div>
    <div className="page-head"><h2>Documents — review queue</h2><p className="page-sub">Checklists, review queue and expiry alerts</p></div>
    {note && <p className="note">{note}</p>}
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="toolbar">
        <div className="field"><label htmlFor="doc-case">Case ID</label><input id="doc-case" inputMode="numeric" value={caseId} onChange={e => setCaseId(e.target.value)} /></div>
        <button onClick={loadChecklist}>Load checklist</button>
        <button onClick={initChecklist}>Init checklist from stream</button>
        <button onClick={packet}>Download submission packet (ZIP)</button>
      </div>
    </div>
    {checklist && (<><h3>Checklist for case #{caseId}</h3><div className="stack" style={{ marginBottom: 18 }}>{checklist.map(itemRow)}</div></>)}
    <h3>Review queue (oldest first — approve or reject to empty it)</h3>
    {queue.length === 0 ? <p className="muted">Queue is empty.</p> : <div className="stack" style={{ marginBottom: 18 }}>{queue.map(itemRow)}</div>}
    <h3>Expiring within 30 days</h3>
    {expiring.length === 0 ? <p className="muted">None.</p> : <ul className="list" style={{ marginBottom: 16 }}>{expiring.map(it => <li className="list-item" key={it.id}><span className="grow"><b>{it.document_name}</b> — case #{it.case_id} ({it.client_name})</span><span className="badge gold">expires {it.expiry_date}</span></li>)}</ul>}
    <button onClick={async () => { const r = await act('/api/jobs/run-expiry-alerts'); setNote(JSON.stringify(r)) }}>Run expiry alerts job</button>
  </div>)
}

function PortalSignIn({ onDone, onBack }) {
  const [identifier, setIdentifier] = useState('aisha@example.com')
  const [firm, setFirm] = useState('demo-firm')
  const [code, setCode] = useState('')
  const [step, setStep] = useState(1)
  const [msg, setMsg] = useState('')
  const request = async () => {
    const res = await api('/api/portal/request-otp', null, { identifier, firm_slug: firm })
    setMsg(res.dev_code ? `Development mode — your code is ${res.dev_code} (no message sent).` : res.detail)
    setStep(2)
  }
  const verify = async () => {
    const res = await api('/api/portal/verify-otp', null, { identifier, firm_slug: firm, code })
    onDone(res.token)
  }
  return (<div className="login-wrap"><div className="card login-card">
    <div className="login-brand"><span className="brand-mark">IC</span><h1>Client portal</h1></div>
    <h2>Sign in with a one-time code</h2>
    {step === 1 ? (<>
      <div className="field"><label htmlFor="ps-id">Email or phone</label>
        <input id="ps-id" value={identifier} onChange={e => setIdentifier(e.target.value)} /></div>
      <div className="field"><label htmlFor="ps-firm">Firm portal (slug)</label>
        <input id="ps-firm" value={firm} onChange={e => setFirm(e.target.value)} /></div>
      <button className="btn btn-block" onClick={request}>Send sign-in code</button>
    </>) : (<>
      <p className="callout">{msg}</p>
      <div className="field"><label htmlFor="ps-code">Code</label>
        <input id="ps-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} /></div>
      <button className="btn btn-block" onClick={verify}>Sign in</button>
    </>)}
    <div className="login-foot"><p><button className="link-btn" onClick={onBack}>Back to staff sign-in</button></p></div>
  </div></div>)
}

function PortalApp({ token, onSignOut }) {
  const [cases, setCases] = useState([])
  const [detail, setDetail] = useState(null)
  const [file, setFile] = useState({})
  const [note, setNote] = useState('')
  const [me, setMe] = useState(null)
  useEffect(() => {
    api('/api/portal/me', token).then(setMe).catch(e => setNote(String(e)))
    api('/api/portal/cases', token).then(setCases).catch(e => setNote(String(e)))
  }, [token])
  const open = async (id) => setDetail(await api(`/api/portal/cases/${id}`, token))
  const up = async (caseId, itemId) => {
    if (!file[itemId]) return
    await upload(`/api/portal/cases/${caseId}/checklist/${itemId}/upload`, token, file[itemId])
    setNote('Uploaded — the firm will review it.')
    open(caseId)
  }
  return (<div className="portal">
    <div className="portal-bar">
      <span className="brand-mark">IC</span>
      <h1>Client portal</h1>
      {me && <span className="who">{me.full_name}</span>}
      <button onClick={onSignOut}>Sign out</button>
    </div>
    <div className="portal-inner">
      {note && <p className="note">{note}</p>}
      <AssistantWidget token={token} cases={cases} />
      <div className="page-head"><h2>Your cases</h2><p className="page-sub">Tap a case to see its documents and messages</p></div>
      {cases.map(c => (<button className="case-card" key={c.id} onClick={() => open(c.id)}>
        <span className="case-top"><b>Case #{c.id} — {c.stream}</b><span className={`badge ${badgeClass(c.stage)}`}>{c.stage}</span></span>
        <span className="meta">Checklist: {Object.entries(c.checklist_counts).filter(([, n]) => n > 0).map(([s, n]) => `${s}: ${n}`).join(', ') || 'none'}
        {c.next_deadline ? ` · Next deadline: ${c.next_deadline.title} (${c.next_deadline.due_date})` : ''}</span>
      </button>))}
      {detail && (<div className="card">
        <h2>Case #{detail.case.id} — {detail.case.stream} · {detail.case.stage}</h2>
        <h3>Documents</h3>
        {detail.checklist.map(it => <div className="doc-row" key={it.id}>
          <div className="doc-head"><b>{it.document_name}</b><span className={`badge ${it.status === 'Approved' ? 'teal' : it.status === 'Rejected' ? 'red' : 'gold'}`}>{it.status}</span></div>
          <p className="doc-meta">
            {it.expiry_date ? `Expires ${it.expiry_date} · ` : ''}
            {it.rejection_reason ? (<span className="attention">Needs attention: {it.rejection_reason} — please re-upload.</span>) : ''}
            {it.latest_version ? `Latest: v${it.latest_version.version_no} ${it.latest_version.original_filename}` : 'Nothing uploaded yet'}
          </p>
          <div className="upload-row"><input type="file" onChange={e => setFile({ ...file, [it.id]: e.target.files[0] })} />
          <button className="btn" onClick={() => up(detail.case.id, it.id)}>Upload</button></div>
        </div>)}
        <h3>Messages from the firm</h3>
        {detail.messages.length === 0 ? <p className="muted">No messages yet.</p> : <ul className="list">{detail.messages.map((m, i) => <li className="list-item" key={i}><span className="grow">[{m.channel}] {m.body} <span className="meta">({m.status})</span></span></li>)}</ul>}
      </div>)}
    </div>
  </div>)
}

function BillingPage({ token, invoices, refresh }) {
  const [templates, setTemplates] = useState([])
  const [cases, setCases] = useState([])
  const [caseId, setCaseId] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [due, setDue] = useState('')
  const [pay, setPay] = useState({})
  const [note, setNote] = useState('')
  useEffect(() => {
    api('/api/billing/templates', token).then(setTemplates).catch(e => setNote(String(e)))
    api('/api/cases', token).then(setCases).catch(e => setNote(String(e)))
  }, [token])
  const create = async () => {
    try {
      await api(`/api/cases/${caseId}/invoices`, token, { template_id: templateId ? Number(templateId) : null, due_date: due || null })
      setNote('Invoice created.'); refresh()
    } catch (e) { setNote(String(e)) }
  }
  const send = async (id) => { await api(`/api/invoices/${id}/send`, token, {}); refresh() }
  const record = async (id) => {
    const p = pay[id] || {}
    await api(`/api/invoices/${id}/payments`, token, { method: p.method || 'e-transfer', amount_cents: Math.round(Number(p.amount || 0) * 100), proof: p.proof || '' })
    refresh()
  }
  return (<div>
    <div className="page-head"><h2>Billing</h2><p className="page-sub">Invoices, instalments and payment receipts</p></div>
    {note && <p className="note">{note}</p>}
    <div className="card" style={{ marginBottom: 16 }}><h3>New invoice from template</h3>
      <div className="form-grid">
        <div className="field"><label htmlFor="bill-case">Case</label><select id="bill-case" value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">—</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select></div>
        <div className="field"><label htmlFor="bill-template">Template</label><select id="bill-template" value={templateId} onChange={e => setTemplateId(e.target.value)}><option value="">—</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
        <div className="field"><label htmlFor="bill-due">Due date</label><input id="bill-due" type="date" value={due} onChange={e => setDue(e.target.value)} /></div>
      </div>
      <button className="btn" onClick={create}>Create</button>
    </div>
    <div className="stack">{invoices.map(inv => <div className="doc-card" key={inv.id}>
      <div className="doc-head"><b>{inv.number}</b><span className={`badge ${inv.status === 'Paid' ? 'teal' : inv.status === 'Sent' ? 'navy' : 'gold'}`}>{inv.status}</span></div>
      <p className="doc-meta">Total ${inv.total_cents / 100} · Paid ${inv.paid_cents / 100}</p>
      {inv.status === 'Draft' && <div className="row-actions" style={{ marginBottom: 10 }}><button onClick={() => send(inv.id)}>Send</button></div>}
      <div className="form-row">
        <div className="field"><label htmlFor={`pay-m-${inv.id}`}>Method</label><select id={`pay-m-${inv.id}`} value={(pay[inv.id] || {}).method || 'e-transfer'} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), method: e.target.value } })}><option>e-transfer</option><option>card</option><option>cash</option></select></div>
        <div className="field"><label htmlFor={`pay-a-${inv.id}`}>Amount ($)</label><input id={`pay-a-${inv.id}`} inputMode="decimal" value={(pay[inv.id] || {}).amount || ''} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), amount: e.target.value } })} /></div>
        <div className="field grow"><label htmlFor={`pay-p-${inv.id}`}>Proof</label><input id={`pay-p-${inv.id}`} value={(pay[inv.id] || {}).proof || ''} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), proof: e.target.value } })} /></div>
        <button className="btn" onClick={() => record(inv.id)}>Record payment</button>
      </div>
    </div>)}</div>
    <p className="note">Payments are recorded, not charged — card, e-transfer, and cash all record the same way.</p>
  </div>)
}

function ReportsPage({ token, summary }) {
  const download = async () => {
    const r = await fetch('/api/reports/export.xlsx', { headers: { Authorization: `Bearer ${token}` } })
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = 'reports.xlsx'; a.click()
  }
  return (<div>
    <div className="page-head"><h2>Reports</h2><p className="page-sub">Approval rates, workload, revenue and stage timing</p></div>
    <div className="toolbar"><button className="btn" onClick={download}>Download spreadsheet for the accountant (.xlsx)</button></div>
    <div className="grid">
      <div className="card"><h3>Approval rate by stream</h3><ul className="kv-list">{Object.entries(summary.approval_rate_by_stream || {}).map(([s, r]) => <li key={s}><span>{s}</span><span className="kv-val">{r.rate === null ? 'n/a (no decided cases)' : `${Math.round(r.rate * 100)}%`} ({r.approved} approved / {r.refused} refused of {r.decided} decided)</span></li>)}</ul></div>
      <div className="card"><h3>Workload</h3><ul className="kv-list">{(summary.workload || []).map((w, i) => <li key={i}><span>{w.assignee}</span><span className="kv-val">{w.open_cases} open cases</span></li>)}</ul></div>
      <div className="card"><h3>Revenue by month</h3><ul className="kv-list">{(summary.revenue_by_month || []).map((r, i) => <li key={i}><span>{r.month}</span><span className="kv-val">received ${r.received_cents / 100} ({r.payments} payments) · invoiced ${r.invoiced_cents / 100} ({r.invoices} invoices)</span></li>)}</ul></div>
      <div className="card"><h3>Days per stage</h3><ul className="kv-list">{(summary.days_per_stage || []).map((d, i) => <li key={i}><span>{d.stream} · {d.stage}</span><span className="kv-val">{d.avg_days} days avg ({d.cases} cases)</span></li>)}</ul></div>
    </div>
  </div>)
}

function SubscriptionBlock({ token }) {
  const [sub, setSub] = useState(null)
  const [note, setNote] = useState('')
  const [plan, setPlan] = useState('starter')
  const [status, setStatus] = useState('active')
  useEffect(() => { api('/api/settings/subscription', token).then(s => { setSub(s); setPlan(s.plan); setStatus(s.status) }).catch(e => setNote(String(e))) }, [token])
  const save = async () => { try { setSub(await patch('/api/settings/subscription', token, { plan, status })) } catch (e) { setNote(String(e)) } }
  if (!sub) return (<div className="card"><h3>Platform subscription</h3>{note && <p className="note">{note}</p>}<p className="muted">Loading… (firm admin only)</p></div>)
  return (<div className="card"><h3>Platform subscription</h3>
    <p>Plan: {sub.plan} · Status: {sub.status} · Seats: {sub.seats} · Renews: {sub.renews_on || '—'}</p>
    <div className="form-row">
      <div className="field"><label htmlFor="sub-plan">Plan</label><select id="sub-plan" value={plan} onChange={e => setPlan(e.target.value)}><option>starter</option><option>growth</option><option>scale</option></select></div>
      <div className="field"><label htmlFor="sub-status">Status</label><select id="sub-status" value={status} onChange={e => setStatus(e.target.value)}><option>active</option><option>trialing</option><option>past_due</option><option>cancelled</option></select></div>
      <button className="btn" onClick={save}>Save</button>
    </div>
    {note && <p className="note">{note}</p>}
  </div>)
}

function AssistantWidget({ token, cases }) {
  const [question, setQuestion] = useState('')
  const [caseId, setCaseId] = useState('')
  const [turn, setTurn] = useState(null)
  const [note, setNote] = useState('')
  const ask = async () => {
    try { setTurn(await api('/api/portal/assistant/ask', token, { question, case_id: caseId ? Number(caseId) : null })) } catch (e) { setNote(String(e)) }
  }
  return (<div className="card assistant-card">
    <h2>Ask about my case</h2>
    <p className="note">Answers come only from your own case file. Anything about eligibility, law, or likely outcomes goes to your consultant.</p>
    <div className="field"><label htmlFor="asst-case">Case</label><select id="asst-case" value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">— first case —</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select></div>
    <div className="form-row">
      <div className="field grow"><label htmlFor="asst-q">Your question</label><input id="asst-q" value={question} onChange={e => setQuestion(e.target.value)} placeholder="e.g. What is happening with my application?" /></div>
      <button className="btn" onClick={ask}>Ask</button>
    </div>
    {turn && (<div style={{ marginTop: 14 }}><p>{turn.answer}</p>{turn.routed && <p className="note">Routed to your consultant — please message the firm through the portal for this one.</p>}</div>)}
    {note && <p className="error">{note}</p>}
  </div>)
}

function RetainersPage({ token, cases }) {
  const [caseId, setCaseId] = useState('')
  const [list, setList] = useState([])
  const [signer, setSigner] = useState('')
  const [note, setNote] = useState('')
  const load = async (id) => { if (!id) return; setList(await api(`/api/cases/${id}/retainers`, token)) }
  const generate = async () => { try { await api(`/api/cases/${caseId}/retainers`, token, {}); await load(caseId); setNote('Retainer generated (draft).') } catch (e) { setNote(String(e)) } }
  const sign = async (id) => { try { await api(`/api/retainers/${id}/sign`, token, { signer_name: signer }); await load(caseId); setNote('Retainer signed in-app (typed name + timestamp + audit row).') } catch (e) { setNote(String(e)) } }
  return (<div>
    <div className="page-head"><h2>Retainers</h2><p className="page-sub">In-app retainer signatures with stage gate</p></div>
    {note && <p className="note">{note}</p>}
    <p className="note">A case cannot leave its opening stage until its retainer is signed — enforced server-side. Signatures here are captured in-app (typed name); there is no third-party e-signature provider in this build.</p>
    <div className="toolbar">
      <div className="field"><label htmlFor="ret-case">Case</label><select id="ret-case" value={caseId} onChange={e => { setCaseId(e.target.value); load(e.target.value) }}><option value="">—</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream} · {c.stage}</option>)}</select></div>
      <button className="btn" disabled={!caseId} onClick={generate}>Generate retainer</button>
    </div>
    <ul className="list">{list.map(r => <li className="list-item" key={r.id}><span className="grow"><b>#{r.id}</b> — {r.status}{r.signed_at ? ` · signed by ${r.signer_name} (${r.method}) at ${r.signed_at}` : ''}</span>
      {r.status === 'draft' && <span className="row-actions"><input value={signer} onChange={e => setSigner(e.target.value)} placeholder="Signer full name" style={{ minWidth: 180 }} /> <button className="btn" onClick={() => sign(r.id)}>Sign in-app</button></span>}
    </li>)}</ul>
  </div>)
}

function FormsPage({ token, cases }) {
  const [caseId, setCaseId] = useState('')
  const [list, setList] = useState([])
  const [code, setCode] = useState('IMM 0008')
  const [detail, setDetail] = useState(null)
  const [corr, setCorr] = useState('')
  const [note, setNote] = useState('')
  const load = async (id) => { if (!id) return; setList(await api(`/api/cases/${id}/ircc-forms`, token)) }
  const generate = async () => { try { await api(`/api/cases/${caseId}/ircc-forms`, token, { form_code: code }); await load(caseId) } catch (e) { setNote(String(e)) } }
  const open = async (id) => { setDetail(await api(`/api/ircc-forms/${id}`, token)) }
  const correct = async () => { try { let c = {}; try { c = JSON.parse(corr || '{}') } catch { setNote('Corrections must be JSON, e.g. {"uci": "1234-5678"}'); return } await patch(`/api/ircc-forms/${detail.id}`, token, { corrections: c }); await load(caseId); setDetail(await api(`/api/ircc-forms/${detail.id}`, token)); setNote('Correction saved as a new version.') } catch (e) { setNote(String(e)) } }
  return (<div>
    <div className="page-head"><h2>IRCC forms</h2><p className="page-sub">Autofilled forms with versioned corrections</p></div>
    {note && <p className="note">{note}</p>}
    <p className="note">Structured form data + printable rendering — NOT official IRCC PDFs. Every consultant correction is a new version; nothing is ever submitted to IRCC by this system.</p>
    <div className="toolbar">
      <div className="field"><label htmlFor="frm-case">Case</label><select id="frm-case" value={caseId} onChange={e => { setCaseId(e.target.value); load(e.target.value); setDetail(null) }}><option value="">—</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select></div>
      <div className="field"><label htmlFor="frm-code">Form</label><select id="frm-code" value={code} onChange={e => setCode(e.target.value)}>{['IMM 0008', 'IMM 5669', 'IMM 5257', 'IMM 1294', 'IMM 5476'].map(f => <option key={f}>{f}</option>)}</select></div>
      <button className="btn" disabled={!caseId} onClick={generate}>Generate from case data</button>
    </div>
    <ul className="list">{list.map(f => <li className="list-item" key={f.id}><button onClick={() => open(f.id)}>{f.form_code} v{f.version_no} ({f.status})</button></li>)}</ul>
    {detail && (<div className="card" style={{ marginTop: 16 }}><h3>{detail.form_code} v{detail.version_no} ({detail.status})</h3><pre>{detail.rendering}</pre>
    <div className="form-row">
      <div className="field grow"><label htmlFor="frm-corr">Correct (JSON)</label><input id="frm-corr" value={corr} onChange={e => setCorr(e.target.value)} placeholder='{"uci": "1234-5678"}' /></div>
      <button className="btn" onClick={correct}>Save as new version</button>
    </div></div>)}
  </div>)
}

function ChasingPage({ token, cases }) {
  const [caseId, setCaseId] = useState('')
  const [list, setList] = useState([])
  const [note, setNote] = useState('')
  const run = async () => { try { const r = await api('/api/jobs/run-chasing', token, {}); setNote(`Chasing run: ${r.chased} sent, ${r.skipped_recent} skipped (already chased within 7 days).`); if (caseId) setList(await api(`/api/cases/${caseId}/chases`, token)) } catch (e) { setNote(String(e)) } }
  const load = async (id) => { if (!id) return; setList(await api(`/api/cases/${id}/chases`, token)) }
  return (<div>
    <div className="page-head"><h2>Document chasing</h2><p className="page-sub">Automatic follow-ups for missing documents</p></div>
    {note && <p className="note">{note}</p>}
    <p className="note">Missing items are chased automatically (log mode by default — nothing is delivered until the firm's sender is verified). Chasing stops when the item arrives and never repeats within 7 days per channel.</p>
    <div className="toolbar">
      <button className="btn" onClick={run}>Run chasing job now</button>
      <div className="field"><label htmlFor="ch-case">Case</label><select id="ch-case" value={caseId} onChange={e => { setCaseId(e.target.value); load(e.target.value) }}><option value="">—</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select></div>
    </div>
    {list.length === 0 ? <p className="muted">No chases for this case yet.</p> : <ul className="list">{list.map(c => <li className="list-item" key={c.id}><span className="grow">Item #{c.checklist_item_id} · {c.channel} · {c.message_status}</span><span className="meta">{c.at}</span></li>)}</ul>}
  </div>)
}

function PrecheckPage({ token }) {
  const [answers, setAnswers] = useState({ education: 'bachelor', language_clb: 7, work_years: 3, age_band: 'under-30', job_offer: false, family_in_canada: false, admission_letter: false, proof_of_funds: false, province_interest: '' })
  const [result, setResult] = useState(null)
  const [note, setNote] = useState('')
  const set = (k, v) => setAnswers({ ...answers, [k]: v })
  const run = async () => { try { setResult(await api('/api/staff/precheck', token, { answers })) } catch (e) { setNote(String(e)) } }
  return (<div>
    <div className="page-head"><h2>Eligibility pre-check</h2><p className="page-sub">Rules-based triage — never a decision</p></div>
    {note && <p className="error">{note}</p>}
    <p className="note">Rules-based triage only. It never decides eligibility, never promises an outcome, and never replaces the consultant's assessment. Every result carries the disclaimer.</p>
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="form-grid">
        <div className="field"><label htmlFor="pc-edu">Education</label><select id="pc-edu" value={answers.education} onChange={e => set('education', e.target.value)}><option value="">—</option><option value="secondary">Secondary</option><option value="diploma">Diploma</option><option value="bachelor">Bachelor</option><option value="master_plus">Master or higher</option></select></div>
        <div className="field"><label htmlFor="pc-clb">Language CLB</label><input id="pc-clb" type="number" value={answers.language_clb} onChange={e => set('language_clb', Number(e.target.value))} /></div>
        <div className="field"><label htmlFor="pc-work">Work years</label><input id="pc-work" type="number" value={answers.work_years} onChange={e => set('work_years', Number(e.target.value))} /></div>
        <div className="field"><label htmlFor="pc-age">Age</label><select id="pc-age" value={answers.age_band} onChange={e => set('age_band', e.target.value)}><option value="">—</option><option value="under-30">Under 30</option><option value="30-40">30–40</option><option value="40-plus">40+</option></select></div>
        <div className="field"><label htmlFor="pc-prov">Province of interest</label><input id="pc-prov" value={answers.province_interest} onChange={e => set('province_interest', e.target.value)} placeholder="e.g. Ontario" /></div>
      </div>
      <div className="checks">
        <label className="check-row"><input type="checkbox" checked={answers.job_offer} onChange={e => set('job_offer', e.target.checked)} /> Job offer</label>
        <label className="check-row"><input type="checkbox" checked={answers.family_in_canada} onChange={e => set('family_in_canada', e.target.checked)} /> Family in Canada</label>
        <label className="check-row"><input type="checkbox" checked={answers.admission_letter} onChange={e => set('admission_letter', e.target.checked)} /> Admission letter</label>
        <label className="check-row"><input type="checkbox" checked={answers.proof_of_funds} onChange={e => set('proof_of_funds', e.target.checked)} /> Proof of funds</label>
      </div>
      <div className="row-actions" style={{ marginTop: 14 }}><button className="btn" onClick={run}>Run pre-check</button></div>
    </div>
    {result && (<div className="card"><h3>Likely streams to explore</h3>
    {result.ranked.length === 0 ? <p className="muted">No strong match from these answers — book a consultation.</p> :
      <ul className="list">{result.ranked.map((r, i) => <li className="list-item" key={i}><span className="grow"><b>{r.stream}</b> — {r.reasons.join('; ')}</span></li>)}</ul>}
    <p className="note">{result.disclaimer}</p></div>)}
  </div>)
}

createRoot(document.getElementById('root')).render(<App />)
