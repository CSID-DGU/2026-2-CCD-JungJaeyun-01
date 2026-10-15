import { useState } from 'react'
import { sendMemo } from '../api'
import { shareToKakaoTalk } from '../kakaoShare'

interface Props {
  text: string
  url: string
  loggedIn: boolean
}

/** 결과 공유: 카카오톡 공유 창(로그인 불필요) / 나에게 보내기(로그인 필요) */
export default function ShareBar({ text, url, loggedIn }: Props) {
  const [status, setStatus] = useState<{ kind: 'ok' | 'error' | 'login'; message: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function share() {
    setStatus(null)
    try {
      await shareToKakaoTalk(text, url)
    } catch (e) {
      setStatus({ kind: 'error', message: e instanceof Error ? e.message : '공유하지 못했어요.' })
    }
  }

  async function toMe() {
    if (!loggedIn) {
      setStatus({ kind: 'login', message: '나에게 보내기는 카카오 로그인이 필요해요.' })
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      await sendMemo(text, url)
      setStatus({ kind: 'ok', message: '카카오톡 "나와의 채팅"으로 보냈어요.' })
    } catch (e) {
      setStatus({ kind: 'error', message: e instanceof Error ? e.message : '보내지 못했어요.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="share-bar">
      <div className="share-buttons">
        <button type="button" className="btn kakao" onClick={share}>카카오톡으로 공유</button>
        <button type="button" className="btn ghost" onClick={toMe} disabled={busy}>
          {busy ? '보내는 중…' : '나에게 보내기'}
        </button>
      </div>
      {status && (
        <p className={`share-status ${status.kind}`} role="status">
          {status.message}
          {status.kind === 'login' && <> <a href="/auth/kakao/login">카카오로 로그인</a></>}
        </p>
      )}
    </div>
  )
}
