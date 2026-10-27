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

function SignIn({ onDone }) {
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
  </div>)
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('icrm_token'))
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
    const path = page === 'dashboard' ? '/api/dashboard' : page === 'leads' ? '/api/leads' : page === 'clients' ? '/api/clients' : page === 'cases' ? '/api/cases' : '/api/settings'
    api(path, token).then(setData).catch(e => setErr(String(e)))
  }, [token, page])
  if (!token) return <SignIn onDone={setToken} />
  const nav = { fontFamily: 'sans-serif', padding: 20 }
  const btn = { marginRight: 8, padding: '6px 12px' }
  return (<div style={nav}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <h1>Immigration Consultant CRM</h1>
      <span>{me ? `${me.full_name} (${me.role}) — ${me.tenant}` : ''} <button onClick={() => { localStorage.removeItem('icrm_token'); setToken(null) }}>Sign out</button></span>
    </div>
    <div style={{ marginBottom: 16 }}>
      {['dashboard', 'leads', 'clients', 'cases', 'settings'].map(p =>
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
    </div>)}
    {page === 'leads' && data && (<Leads token={token} leads={data} refresh={() => api('/api/leads', token).then(setData)} />)}
    {page === 'clients' && data && (<div><h2>Clients</h2><ul>{data.map(c => <li key={c.id}>{c.full_name} — {c.email} {c.phone}</li>)}</ul></div>)}
    {page === 'cases' && data && (<div><h2>Cases</h2><ul>{data.map(c => <li key={c.id}>Case #{c.id} — {c.stream} · {c.stage} · File {c.ircc_file_number || '—'}</li>)}</ul></div>)}
    {page === 'settings' && data && (<div><h2>Settings</h2><p>Firm: {data.firm}</p>
      <h3>Branches</h3><ul>{data.branches.map(b => <li key={b.id}>{b.name} ({b.city})</li>)}</ul>
      <h3>Team</h3><ul>{data.team.map(u => <li key={u.id}>{u.full_name} — {u.role} — {u.email}</li>)}</ul></div>)}
  </div>)
}

function Leads({ token, leads, refresh }) {
  const [name, setName] = useState('')
  const [stream, setStream] = useState('Express Entry')
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
      {' '}<button onClick={() => move(l.id, 'Contacted')}>Contacted</button>
      <button onClick={() => move(l.id, 'Qualified')}>Qualified</button>
      <button onClick={() => move(l.id, 'Consultation')}>Consultation</button>
      {l.stage !== 'Converted' && l.stage !== 'Lost' && <button onClick={() => convert(l.id)}>Convert to client + case</button>}
      <button onClick={() => move(l.id, 'Lost')}>Lost</button></li>)}</ul>
  </div>)
}

createRoot(document.getElementById('root')).render(<App />)
