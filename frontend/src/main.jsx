import React, { useState, useEffect } from 'react'
import { createRoot } from 'react-dom/client'

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
  return (<div style={{ maxWidth: 420, margin: '80px auto', fontFamily: 'sans-serif' }}>
    <h1>Immigration Consultant CRM</h1><h2>Sign in to your firm</h2>
    {step === 1 ? (<>
      <label>Work email address<br /><input value={email} onChange={e => setEmail(e.target.value)} style={{ width: '100%', padding: 8 }} /></label>
      <button onClick={request} style={{ marginTop: 12, padding: '8px 16px' }}>Send sign-in code</button>
    </>) : (<>
      <p>{msg}</p>
      <label>Code<br /><input value={code} onChange={e => setCode(e.target.value)} style={{ width: '100%', padding: 8 }} /></label>
      <button onClick={verify} style={{ marginTop: 12, padding: '8px 16px' }}>Sign in</button>
    </>)}
    <p><button onClick={onPortal} style={{ padding: '6px 12px' }}>I am a client — open the client portal</button></p>
  </div>)
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('icrm_token'))
  const [portalToken, setPortalToken] = useState(localStorage.getItem('icrm_portal_token'))
  const [portal, setPortal] = useState(false)
  const [page, setPage] = useState('dashboard')
  const [me, setMe] = useState(null)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!token) return
    api('/api/me', token).then(setMe).catch(() => { localStorage.removeItem('icrm_token'); setToken(null) })
  }, [token])
  useEffect(() => {
    if (!token) return
    const path = page === 'dashboard' ? '/api/dashboard' : page === 'leads' ? '/api/leads' : page === 'clients' ? '/api/clients' : page === 'cases' ? '/api/cases' : page === 'messages' ? '/api/cases' : page === 'calendar' ? '/api/consultations' : page === 'comms' ? '/api/settings/communications' : page === 'documents' ? '/api/review-queue' : page === 'billing' ? '/api/invoices' : page === 'reports' ? '/api/reports/summary' : '/api/settings'
    api(path, token).then(setData).catch(e => setErr(String(e)))
  }, [token, page])
  if (portalToken) return <PortalApp token={portalToken} onSignOut={() => { localStorage.removeItem('icrm_portal_token'); setPortalToken(null); setPortal(false) }} />
  if (portal) return <PortalSignIn onDone={(t) => { localStorage.setItem('icrm_portal_token', t); setPortalToken(t) }} onBack={() => setPortal(false)} />
  if (!token) return <SignIn onDone={setToken} onPortal={() => setPortal(true)} />
  const nav = { fontFamily: 'sans-serif', padding: 20 }
  const btn = { marginRight: 8, padding: '6px 12px' }
  return (<div style={nav}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <h1>Immigration Consultant CRM</h1>
      <span>{me ? `${me.full_name} (${me.role}) — ${me.tenant}` : ''} <button onClick={() => { localStorage.removeItem('icrm_token'); setToken(null) }}>Sign out</button></span>
    </div>
    <div style={{ marginBottom: 16 }}>
      {['dashboard', 'leads', 'clients', 'cases', 'messages', 'calendar', 'documents', 'billing', 'reports', 'comms', 'settings'].map(p =>
        <button key={p} style={btn} onClick={() => { setPage(p); setData(null); setErr('') }}>{p}</button>)}
    </div>
    {err && <p style={{ color: 'red' }}>{err}</p>}
    {!data && !err && <p>Loading…</p>}
    {page === 'dashboard' && data && (<div>
      <h2>Firm dashboard</h2>
      <p>Active cases: <b>{data.active_cases}</b> · Total leads: <b>{data.total_leads}</b></p>
      <h3>Leads by stage</h3><ul>{Object.entries(data.leads_by_stage).map(([s, n]) => <li key={s}>{s}: {n}</li>)}</ul>
      <h3>Cases by stream</h3><ul>{Object.entries(data.cases_by_stream).map(([s, n]) => <li key={s}>{s}: {n}</li>)}</ul>
      <h3>Upcoming follow-ups</h3><ul>{data.upcoming_follow_ups.map((u, i) => <li key={i}>{u.date} — {u.name} ({u.type})</li>)}</ul>
      <h3>Action items (failed sends, reminders, syncs)</h3><ul>{(data.action_items || []).map(a => <li key={a.id}>{a.title} — {a.detail}</li>)}</ul>
      <h3>Upcoming deadlines</h3><ul>{(data.upcoming_deadlines || []).map(d => <li key={d.id}>{d.due_date} — {d.title} (case #{d.case_id})</li>)}</ul>
      <h3>Upcoming consultations</h3><ul>{(data.upcoming_consultations || []).map(c => <li key={c.id}>{c.starts_at} — {c.kind} ({c.status})</li>)}</ul>
    </div>)}
    {page === 'documents' && data && (<DocumentsPage token={token} />)}
    {page === 'billing' && data && (<BillingPage token={token} invoices={data} refresh={() => api('/api/invoices', token).then(setData)} />)}
    {page === 'reports' && data && (<ReportsPage token={token} summary={data} />)}
    {page === 'messages' && data && (<MessagesPage token={token} cases={data} />)}
    {page === 'calendar' && data && (<CalendarPage token={token} consultations={data} />)}
    {page === 'comms' && data && (<CommsPage token={token} comms={data} />)}
    {page === 'leads' && data && (<Leads token={token} leads={data} refresh={() => api('/api/leads', token).then(setData)} />)}
    {page === 'clients' && data && (<div><h2>Clients</h2><ul>{data.map(c => <li key={c.id}>{c.full_name} — {c.email} {c.phone}</li>)}</ul></div>)}
    {page === 'cases' && data && (<div><h2>Cases</h2><ul>{data.map(c => <li key={c.id}>Case #{c.id} — {c.stream} · {c.stage} · File {c.ircc_file_number || '—'}</li>)}</ul></div>)}
    {page === 'settings' && data && (<div><h2>Settings</h2><p>Firm: {data.firm}</p>
      <h3>Branches</h3><ul>{data.branches.map(b => <li key={b.id}>{b.name} ({b.city})</li>)}</ul>
      <h3>Team</h3><ul>{data.team.map(u => <li key={u.id}>{u.full_name} — {u.role} — {u.email}</li>)}</ul>
      <SubscriptionBlock token={token} /></div>)}
  </div>)
}

function Leads({ token, leads, refresh }) {
  const [name, setName] = useState('')
  const [stream, setStream] = useState('Express Entry')
  const [detailId, setDetailId] = useState(null)
  const add = async () => {
    if (!name.trim()) return
    await api('/api/leads', token, { full_name: name, stream_of_interest: stream })
    setName(''); refresh()
  }
  const move = async (id, stage) => { await patch(`/api/leads/${id}`, token, { stage }); refresh() }
  const convert = async (id) => { await api(`/api/leads/${id}/convert`, token, {}, 'POST'); refresh() }
  return (<div><h2>Leads pipeline</h2>
    <div><input placeholder="New lead name" value={name} onChange={e => setName(e.target.value)} />
      <select value={stream} onChange={e => setStream(e.target.value)}>{['Express Entry', 'PNP', 'LMIA', 'Study', 'Work', 'Family Sponsorship'].map(s => <option key={s}>{s}</option>)}</select>
      <button onClick={add}>Add lead</button></div>
    <ul>{leads.map(l => <li key={l.id}>{l.full_name} — {l.stream_of_interest} · <b>{l.stage}</b>
      {' '}<button onClick={() => setDetailId(detailId === l.id ? null : l.id)}>Details</button>
      <button onClick={() => move(l.id, 'Contacted')}>Contacted</button>
      <button onClick={() => move(l.id, 'Qualified')}>Qualified</button>
      <button onClick={() => move(l.id, 'Consultation')}>Consultation</button>
      {l.stage !== 'Converted' && l.stage !== 'Lost' && <button onClick={() => convert(l.id)}>Convert to client + case</button>}
      <button onClick={() => move(l.id, 'Lost')}>Lost</button>
      {detailId === l.id && <LeadDetail token={token} lead={l} />}</li>)}</ul>
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
  return (<div style={{ marginLeft: 20, borderLeft: '2px solid #ccc', paddingLeft: 10 }}>
    <p>Contact: {lead.email} {lead.phone} · Source: {lead.source} · Notes: {lead.notes || '—'}</p>
    <h4>Inline booking (Feature 13)</h4>
    <p>Consultant id <input value={consultantId} onChange={e => setConsultantId(e.target.value)} style={{ width: 60 }} />{' '}
    Start <input placeholder="2026-11-05T10:00:00" value={starts} onChange={e => setStarts(e.target.value)} />{' '}
    End <input placeholder="2026-11-05T10:30:00" value={ends} onChange={e => setEnds(e.target.value)} />{' '}
    <button onClick={book}>Book for this lead</button></p>
    {note && <p>{note}</p>}
    <h4>Messages for this lead</h4>
    <ul>{msgs.map(m => <li key={m.id}>[{m.channel}] {m.status} — {m.body}</li>)}</ul>
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
  return (<div><h2>Case messages + AI drafts</h2>
    <label>Case <select value={caseId} onChange={e => setCaseId(e.target.value)}>{cases.map(c => <option key={c.id} value={c.id}>Case #{c.id} — {c.stream} ({c.stage})</option>)}</select></label>
    {note && <p>{note}</p>}
    <h3>Message log (chronological, SMS + email)</h3>
    <ul>{msgs.map(m => <li key={m.id}>[{m.channel}] {m.status} — {m.body} <i>({m.source}{m.draft_id ? `, draft #${m.draft_id}` : ''})</i></li>)}</ul>
    <h3>Compose</h3>
    <select value={channel} onChange={e => setChannel(e.target.value)}><option value="sms">SMS</option><option value="email">Email</option></select>{' '}
    <input placeholder="Message text" value={body} onChange={e => setBody(e.target.value)} style={{ width: 360 }} />{' '}
    <button onClick={send}>Send (staff)</button>
    <h3>AI drafts (human gate — drafts never send themselves)</h3>
    <button onClick={() => draft('document_request')}>Draft document request</button>{' '}
    <button onClick={() => draft('deadline_summary')}>Draft deadline summary</button>
    <ul>{drafts.map(d => <li key={d.id}>{d.kind} ({d.channel}) — {d.status}: {d.body}{' '}
      {d.status === 'draft' && <button onClick={() => approve(d.id)}>Approve + send</button>}</li>)}</ul>
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
  return (<div><h2>Calendar + consultations (week view)</h2>
    <p>Consultant id <input value={consultantId} onChange={e => setConsultantId(e.target.value)} style={{ width: 60 }} />{' '}
    Start <input placeholder="2026-11-05T10:00:00" value={starts} onChange={e => setStarts(e.target.value)} />{' '}
    End <input placeholder="2026-11-05T10:30:00" value={ends} onChange={e => setEnds(e.target.value)} /></p>
    <button onClick={book}>Book consultation</button>{' '}<button onClick={loadWeek}>Load week view</button>
    {note && <p>{note}</p>}
    <h3>Consultations</h3><ul>{consultations.map(c => <li key={c.id}>#{c.id} — {c.kind} {c.starts_at} ({c.status}, {c.source}, sync {c.sync_status})</li>)}</ul>
    {week && (<><h3>Week view</h3>
      <p>Bookings: {week.consultations.length} · Blocked (Google) slots: {week.blocked_slots.length} · Deadlines: {week.deadlines.length}</p>
      <ul>{week.blocked_slots.map(b => <li key={b.id}>BLOCKED {b.starts_at}–{b.ends_at} ({b.title})</li>)}</ul>
      <ul>{week.deadlines.map(d => <li key={d.id}>DEADLINE {d.due_date} — {d.title}</li>)}</ul></>)}
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
  return (<div><h2>Communications settings (firm admin)</h2>
    <p>SMS mode <select value={s.sms_mode} onChange={e => setS({ ...s, sms_mode: e.target.value })}><option value="log">log (default — would send only)</option><option value="live">live</option></select>{' '}
    Sender <input value={s.sms_sender} onChange={e => setS({ ...s, sms_sender: e.target.value })} />{' '}
    Verified: {String(s.sms_sender_verified)} · Test received: {String(s.sms_test_received)}</p>
    <p>Email mode <select value={s.email_mode} onChange={e => setS({ ...s, email_mode: e.target.value })}><option value="log">log (default)</option><option value="live">live</option></select>{' '}
    Sender <input value={s.email_sender} onChange={e => setS({ ...s, email_sender: e.target.value })} />{' '}
    Verified: {String(s.email_sender_verified)} · Test received: {String(s.email_test_received)}</p>
    <p>Opt-out wording <input value={s.opt_out_wording} onChange={e => setS({ ...s, opt_out_wording: e.target.value })} style={{ width: 320 }} /></p>
    <button onClick={save}>Save settings</button>{' '}
    <button onClick={() => gate('verify-sender', 'sms')}>Verify SMS sender</button>{' '}
    <button onClick={() => gate('verify-sender', 'email')}>Verify email sender</button>{' '}
    <button onClick={() => gate('confirm-test-received', 'sms')}>Confirm SMS test received</button>{' '}
    <button onClick={() => gate('confirm-test-received', 'email')}>Confirm email test received</button>
    {note && <p>{note}</p>}
    <h3>Templates (firm-editable)</h3>
    <ul>{comms.templates.map(t => <li key={t.id}>{t.key} ({t.channel}): {t.subject ? t.subject + ' — ' : ''}{t.body}</li>)}</ul>
    <p><i>Live sending requires sender verification AND a received test message, per channel. Log mode is the default and never delivers.</i></p>
  </div>)
}

function Suggestions({ suggestions, token, refresh }) {
  if (!suggestions || !suggestions.length) return null
  return (<div style={{ border: '1px dashed #888', padding: 8, marginTop: 6 }}>
    <b>AI suggestions (panel — nothing is saved until staff approve)</b>
    <ul>{suggestions.map(s => <li key={s.id}>
      [{s.kind}] {s.proposed_field}: {s.proposed_value}
      {s.source_excerpt ? ` — “${s.source_excerpt}”` : ''} ({s.status})
      {s.status === 'Pending' && (<>
        <button onClick={async () => { await api(`/api/suggestions/${s.id}/approve`, token, {}); refresh() }}>Approve</button>{' '}
        <button onClick={async () => { await api(`/api/suggestions/${s.id}/reject`, token, {}); refresh() }}>Dismiss</button>
      </>)}
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
  const itemRow = (it) => (<li key={it.id}>
    <b>{it.document_name}</b> ({it.person}) — {it.status}
    {it.expiry_date ? ` · expires ${it.expiry_date}` : ''}
    {it.rejection_reason ? ` · rejected: ${it.rejection_reason}` : ''}
    {it.latest_version ? ` · v${it.latest_version.version_no} ${it.latest_version.original_filename} (${it.latest_version.review_decision})` : ''}
    <Suggestions suggestions={it.latest_version ? it.latest_version.suggestions : []} token={token} refresh={refresh} />
    <div>
      <button onClick={() => act(`/api/checklist-items/${it.id}/request`)}>Request</button>{' '}
      <button onClick={() => act(`/api/checklist-items/${it.id}/start-review`)}>Start review</button>{' '}
      <button onClick={() => act(`/api/checklist-items/${it.id}/approve`)}>Approve</button>{' '}
      <input placeholder="Rejection reason" value={reason[it.id] || ''} onChange={e => setReason({ ...reason, [it.id]: e.target.value })} />{' '}
      <button onClick={() => act(`/api/checklist-items/${it.id}/reject`, { reason: reason[it.id] || '' })}>Reject with reason</button>{' '}
      <input type="file" onChange={e => setFile({ ...file, [it.id]: e.target.files[0] })} />{' '}
      <button onClick={async () => { if (file[it.id]) { await upload(`/api/checklist-items/${it.id}/upload`, token, file[it.id]); setNote('Uploaded.'); refresh() } }}>Upload (staff)</button>
    </div>
  </li>)
  return (<div><h2>Documents — review queue (W7)</h2>
    {note && <p>{note}</p>}
    <p>Case ID <input value={caseId} onChange={e => setCaseId(e.target.value)} />{' '}
    <button onClick={loadChecklist}>Load checklist</button>{' '}
    <button onClick={initChecklist}>Init checklist from stream</button>{' '}
    <button onClick={packet}>Download submission packet (ZIP)</button></p>
    {checklist && (<><h3>Checklist for case #{caseId}</h3><ul>{checklist.map(itemRow)}</ul></>)}
    <h3>Review queue (oldest first — approve or reject to empty it)</h3>
    {queue.length === 0 ? <p>Queue is empty.</p> : <ul>{queue.map(itemRow)}</ul>}
    <h3>Expiring within 30 days</h3>
    {expiring.length === 0 ? <p>None.</p> : <ul>{expiring.map(it => <li key={it.id}>{it.document_name} — case #{it.case_id} ({it.client_name}) — expires {it.expiry_date}</li>)}</ul>}
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
  return (<div style={{ maxWidth: 420, margin: '80px auto', fontFamily: 'sans-serif' }}>
    <h1>Client portal</h1><h2>Sign in with a one-time code</h2>
    {step === 1 ? (<>
      <label>Email or phone<br /><input value={identifier} onChange={e => setIdentifier(e.target.value)} style={{ width: '100%', padding: 8 }} /></label><br />
      <label>Firm portal (slug)<br /><input value={firm} onChange={e => setFirm(e.target.value)} style={{ width: '100%', padding: 8 }} /></label>
      <button onClick={request} style={{ marginTop: 12, padding: '8px 16px' }}>Send sign-in code</button>
    </>) : (<>
      <p>{msg}</p>
      <label>Code<br /><input value={code} onChange={e => setCode(e.target.value)} style={{ width: '100%', padding: 8 }} /></label>
      <button onClick={verify} style={{ marginTop: 12, padding: '8px 16px' }}>Sign in</button>
    </>)}
    <p><button onClick={onBack} style={{ padding: '6px 12px' }}>Back to staff sign-in</button></p>
  </div>)
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
  return (<div style={{ fontFamily: 'sans-serif', padding: 20 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <h1>Client portal</h1>
      <span>{me ? me.full_name : ''} <button onClick={onSignOut}>Sign out</button></span>
    </div>
    {note && <p>{note}</p>}
    <AssistantWidget token={token} cases={cases} />
    <h2>Your cases</h2>
    <ul>{cases.map(c => <li key={c.id}>
      <button onClick={() => open(c.id)}>Case #{c.id} — {c.stream} · {c.stage}</button>{' '}
      Checklist: {Object.entries(c.checklist_counts).filter(([, n]) => n > 0).map(([s, n]) => `${s}: ${n}`).join(', ') || 'none'}
      {c.next_deadline ? ` · Next deadline: ${c.next_deadline.title} (${c.next_deadline.due_date})` : ''}
    </li>)}</ul>
    {detail && (<div>
      <h2>Case #{detail.case.id} — {detail.case.stream} · {detail.case.stage}</h2>
      <h3>Documents</h3>
      <ul>{detail.checklist.map(it => <li key={it.id}>
        <b>{it.document_name}</b> — {it.status}
        {it.expiry_date ? ` · expires ${it.expiry_date}` : ''}
        {it.rejection_reason ? (<span style={{ color: 'red' }}> · Needs attention: {it.rejection_reason} — please re-upload.</span>) : ''}
        {it.latest_version ? ` · latest: v${it.latest_version.version_no} ${it.latest_version.original_filename}` : ''}
        <div><input type="file" onChange={e => setFile({ ...file, [it.id]: e.target.files[0] })} />{' '}
        <button onClick={() => up(detail.case.id, it.id)}>Upload</button></div>
      </li>)}</ul>
      <h3>Messages from the firm</h3>
      <ul>{detail.messages.map((m, i) => <li key={i}>[{m.channel}] {m.body} ({m.status})</li>)}</ul>
    </div>)}
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
  return (<div><h2>Billing</h2>{note && <p>{note}</p>}
    <h3>New invoice from template</h3>
    <p>Case: <select value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">—</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select>{' '}
    Template: <select value={templateId} onChange={e => setTemplateId(e.target.value)}><option value="">—</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>{' '}
    Due: <input type="date" value={due} onChange={e => setDue(e.target.value)} />{' '}
    <button onClick={create}>Create</button></p>
    <ul>{invoices.map(inv => <li key={inv.id}>
      <b>{inv.number}</b> — ${inv.total_cents / 100} · paid ${inv.paid_cents / 100} · {inv.status}
      {inv.status === 'Draft' && <button onClick={() => send(inv.id)}>Send</button>}
      <span> · Pay: <select value={(pay[inv.id] || {}).method || 'e-transfer'} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), method: e.target.value } })}><option>e-transfer</option><option>card</option><option>cash</option></select>{' '}
      $<input size={8} value={(pay[inv.id] || {}).amount || ''} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), amount: e.target.value } })} />{' '}
      proof <input size={12} value={(pay[inv.id] || {}).proof || ''} onChange={e => setPay({ ...pay, [inv.id]: { ...(pay[inv.id] || {}), proof: e.target.value } })} />{' '}
      <button onClick={() => record(inv.id)}>Record payment</button></span>
    </li>)}</ul>
    <p><i>Payments are recorded, not charged — card, e-transfer, and cash all record the same way.</i></p>
  </div>)
}

function ReportsPage({ token, summary }) {
  const download = async () => {
    const r = await fetch('/api/reports/export.xlsx', { headers: { Authorization: `Bearer ${token}` } })
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = 'reports.xlsx'; a.click()
  }
  return (<div><h2>Reports</h2>
    <p><button onClick={download}>Download spreadsheet for the accountant (.xlsx)</button></p>
    <h3>Approval rate by stream</h3><ul>{Object.entries(summary.approval_rate_by_stream || {}).map(([s, r]) => <li key={s}>{s}: {r.rate === null ? 'n/a (no decided cases)' : `${Math.round(r.rate * 100)}%`} ({r.approved} approved / {r.refused} refused of {r.decided} decided)</li>)}</ul>
    <h3>Workload</h3><ul>{(summary.workload || []).map((w, i) => <li key={i}>{w.assignee}: {w.open_cases} open cases</li>)}</ul>
    <h3>Revenue by month</h3><ul>{(summary.revenue_by_month || []).map((r, i) => <li key={i}>{r.month}: received ${r.received_cents / 100} ({r.payments} payments) · invoiced ${r.invoiced_cents / 100} ({r.invoices} invoices)</li>)}</ul>
    <h3>Days per stage</h3><ul>{(summary.days_per_stage || []).map((d, i) => <li key={i}>{d.stream} · {d.stage}: {d.avg_days} days avg ({d.cases} cases)</li>)}</ul>
  </div>)
}

function SubscriptionBlock({ token }) {
  const [sub, setSub] = useState(null)
  const [note, setNote] = useState('')
  const [plan, setPlan] = useState('starter')
  const [status, setStatus] = useState('active')
  useEffect(() => { api('/api/settings/subscription', token).then(s => { setSub(s); setPlan(s.plan); setStatus(s.status) }).catch(e => setNote(String(e))) }, [token])
  const save = async () => { try { setSub(await patch('/api/settings/subscription', token, { plan, status })) } catch (e) { setNote(String(e)) } }
  if (!sub) return (<div><h3>Platform subscription</h3>{note && <p>{note}</p>}<p>Loading… (firm admin only)</p></div>)
  return (<div><h3>Platform subscription</h3>
    <p>Plan: {sub.plan} · Status: {sub.status} · Seats: {sub.seats} · Renews: {sub.renews_on || '—'}</p>
    <p>Plan: <select value={plan} onChange={e => setPlan(e.target.value)}><option>starter</option><option>growth</option><option>scale</option></select>{' '}
    Status: <select value={status} onChange={e => setStatus(e.target.value)}><option>active</option><option>trialing</option><option>past_due</option><option>cancelled</option></select>{' '}
    <button onClick={save}>Save</button></p>{note && <p>{note}</p>}
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
  return (<div style={{ border: '1px solid #ccc', padding: 12, marginBottom: 16 }}>
    <h2>Ask about my case</h2>
    <p><i>Answers come only from your own case file. Anything about eligibility, law, or likely outcomes goes to your consultant.</i></p>
    <p>Case: <select value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">— first case —</option>{cases.map(c => <option key={c.id} value={c.id}>#{c.id} {c.stream}</option>)}</select></p>
    <p><input value={question} onChange={e => setQuestion(e.target.value)} placeholder="e.g. What is happening with my application?" style={{ width: '70%', padding: 8 }} />{' '}
    <button onClick={ask}>Ask</button></p>
    {turn && (<div><p>{turn.answer}</p>{turn.routed && <p><i>Routed to your consultant — please message the firm through the portal for this one.</i></p>}</div>)}
    {note && <p>{note}</p>}
  </div>)
}

createRoot(document.getElementById('root')).render(<App />)
