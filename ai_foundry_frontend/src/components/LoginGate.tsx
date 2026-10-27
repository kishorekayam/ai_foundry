import { LockKeyhole } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../api'
import { AUTH_EVENT, clearCredentials, setCredentials } from '../api/auth'
import { Alert, Button, Card, Field, Input } from './ui'
import { Logo } from './Layout'

/** Shows a sign-in form (HTTP Basic) when the API requires credentials and none are accepted yet. */
export default function LoginGate({ children }: { children: ReactNode }) {
  const needsAuth = api.mode === 'http' && !!api.checkAuth
  const [state, setState] = useState<'checking' | 'login' | 'ok'>(needsAuth ? 'checking' : 'ok')
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState<string>()
  const [busy, setBusy] = useState(false)

  const verify = useCallback(async () => {
    try {
      await api.checkAuth!()
      setState('ok')
    } catch {
      setState('login')
    }
  }, [])

  useEffect(() => {
    if (!needsAuth) return
    void verify()
    const onAuth = () => setState('login')
    window.addEventListener(AUTH_EVENT, onAuth)
    return () => window.removeEventListener(AUTH_EVENT, onAuth)
  }, [needsAuth, verify])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(undefined)
    setCredentials(user, pw)
    try {
      await api.checkAuth!()
      setPw('')
      setState('ok')
    } catch (ex) {
      clearCredentials()
      setErr((ex as Error).message === 'Sign in required.' ? 'Username or password is incorrect.' : 'Could not reach the API. Check that the backend is running.')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'ok') return <>{children}</>
  if (state === 'checking') return <div className="grid min-h-full place-items-center text-sm text-slate-500">Connecting…</div>

  return (
    <div className="grid min-h-full place-items-center px-4">
      <Card className="w-full max-w-sm">
        <form onSubmit={submit} className="space-y-4 p-6">
          <div className="flex items-center gap-3">
            <Logo size={36} />
            <div>
              <div className="text-sm font-bold tracking-wide">ATOM DATA FOUNDRY</div>
              <div className="flex items-center gap-1 text-xs text-slate-500"><LockKeyhole className="size-3" /> Sign in to the API</div>
            </div>
          </div>
          <Field label="Username"><Input autoFocus autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} /></Field>
          <Field label="Password"><Input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          {err && <Alert tone="error">{err}</Alert>}
          <Button type="submit" className="w-full" loading={busy} disabled={!user || !pw}>Sign in</Button>
        </form>
      </Card>
    </div>
  )
}
