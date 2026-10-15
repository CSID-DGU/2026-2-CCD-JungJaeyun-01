import { BRAND } from '../brand'
import {
  AGE_OPTIONS,
  MAX_PARTICIPANTS,
  MIN_PARTICIPANTS,
  PARTICIPANT_COLORS,
  PURPOSE_OPTIONS,
} from '../constants'
import { seoulNowInput } from '../meeting'
import type { AgeGroup, Purpose } from '../types'
import type { FieldErrors, FormParticipant } from '../validate'
import PlaceAutocomplete from './PlaceAutocomplete'

interface Props {
  participants: FormParticipant[]
  purpose: Purpose
  /** 약속 시간 (서울 시각, 'YYYY-MM-DDTHH:mm') */
  meetingTime: string
  meetingError: string | null
  errors: FieldErrors
  loading: boolean
  submitError: string | null
  onChangeParticipant: (key: number, patch: Partial<FormParticipant>) => void
  onAdd: () => void
  onRemove: (key: number) => void
  onPurpose: (purpose: Purpose) => void
  onMeetingTime: (value: string) => void
  onSubmit: () => void
}

export default function InputForm(props: Props) {
  const { participants, purpose, meetingTime, meetingError, errors, loading, submitError } = props
  const count = participants.length

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault()
        props.onSubmit()
      }}
      noValidate
    >
      <header className="panel-header">
        <h1>{BRAND.slogan}</h1>
        <p>{BRAND.tagline}</p>
      </header>

      <section aria-label="참여자">
        <div className="section-title">
          <h2>참여자 ({count}/{MAX_PARTICIPANTS})</h2>
          <button
            type="button"
            className="btn ghost"
            onClick={props.onAdd}
            disabled={count >= MAX_PARTICIPANTS}
          >
            + 추가
          </button>
        </div>

        {participants.map((p, i) => {
          const err = errors[p.key]
          return (
            <div className="participant-card" key={p.key}>
              <div className="card-head">
                <span className="dot" style={{ background: PARTICIPANT_COLORS[i] }} />
                <strong>참여자 {i + 1}</strong>
                <button
                  type="button"
                  className="btn icon"
                  aria-label={`참여자 ${i + 1} 삭제`}
                  onClick={() => props.onRemove(p.key)}
                  disabled={count <= MIN_PARTICIPANTS}
                >
                  삭제
                </button>
              </div>

              <div className="row">
                <label className="field grow">
                  <span>이름</span>
                  <input
                    type="text"
                    maxLength={20}
                    value={p.name}
                    className={err?.name ? 'invalid' : ''}
                    onChange={(e) => props.onChangeParticipant(p.key, { name: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>연령대</span>
                  <select
                    value={p.age}
                    onChange={(e) => props.onChangeParticipant(p.key, { age: e.target.value as AgeGroup })}
                  >
                    {AGE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {err?.name && <p className="field-error">{err.name}</p>}

              <div className="field">
                <label htmlFor={`origin-${p.key}`}>출발지</label>
                <PlaceAutocomplete
                  id={`origin-${p.key}`}
                  value={p.origin}
                  hasError={!!err?.origin}
                  onChange={(hit) => props.onChangeParticipant(p.key, { origin: hit })}
                />
                {err?.origin && <p className="field-error">{err.origin}</p>}
              </div>
            </div>
          )
        })}
      </section>

      <section aria-label="모임 조건">
        <div className="section-title">
          <h2>모임 목적</h2>
        </div>
        <div className="segmented" role="radiogroup" aria-label="모임 목적">
          {PURPOSE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={purpose === o.value}
              className={purpose === o.value ? 'active' : ''}
              onClick={() => props.onPurpose(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="transport">
          이동수단 <span className="chip">대중교통</span>
          <small>현재 대중교통만 지원해요</small>
        </p>

        <div className="field meeting">
          <label htmlFor="meeting-time">약속 시간</label>
          <input
            id="meeting-time"
            type="datetime-local"
            value={meetingTime}
            min={seoulNowInput()}
            className={meetingError ? 'invalid' : ''}
            onChange={(e) => props.onMeetingTime(e.target.value)}
          />
          <small className="hint">이 시각에 도착하는 기준으로 이동시간과 출발 시각을 계산해요. (기본: 다음 토요일 오후 6시)</small>
          {meetingError && <p className="field-error">{meetingError}</p>}
        </div>
      </section>

      {submitError && (
        <div className="alert error" role="alert">
          {submitError}
        </div>
      )}

      <button type="submit" className="btn primary block" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner" /> 추천 계산 중…
          </>
        ) : (
          '추천 받기'
        )}
      </button>
    </form>
  )
}
