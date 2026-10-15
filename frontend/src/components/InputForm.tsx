import { Beer, Coffee, MapPin, Plus, SearchX, Utensils, type LucideIcon } from 'lucide-react'
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
import LoadingWalk from './LoadingWalk'
import PlaceAutocomplete from './PlaceAutocomplete'
import StateMessage from './StateMessage'
import Stepper from './Stepper'

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

const PURPOSE_ICONS: Record<Purpose, LucideIcon> = { meal: Utensils, cafe: Coffee, drink: Beer }

/** 이름 첫 글자 (비었으면 순번) */
const initialOf = (name: string, i: number) => [...name.trim()][0] ?? String(i + 1)

export default function InputForm(props: Props) {
  const { participants, purpose, meetingTime, meetingError, errors, loading, submitError } = props
  const count = participants.length

  const peopleReady = participants.every((p) => p.name.trim() && p.origin)
  const ready = peopleReady && !!meetingTime
  const step = !peopleReady ? 1 : !meetingTime ? 2 : 3
  const missing = !peopleReady
    ? participants.some((p) => !p.origin)
      ? '모든 참여자의 출발지를 선택하면 추천을 받을 수 있어요'
      : '모든 참여자의 이름을 입력해 주세요'
    : !meetingTime
      ? '약속 시간을 입력해 주세요'
      : null

  if (loading) return <LoadingWalk />

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) props.onSubmit()
      }}
      noValidate
    >
      <header className="panel-header">
        <h1>{BRAND.slogan}</h1>
        <p>{BRAND.tagline}</p>
      </header>

      <Stepper current={step} />

      <section aria-label="참여자">
        <div className="section-title">
          <h2>참여자 <span className="count-badge">{count}/{MAX_PARTICIPANTS}</span></h2>
        </div>

        {participants.map((p, i) => {
          const err = errors[p.key]
          const color = PARTICIPANT_COLORS[i]
          return (
            <div className="participant-card" key={p.key}>
              <div className="card-head">
                <span className="avatar" style={{ background: color }} aria-hidden="true">{initialOf(p.name, i)}</span>
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
                <div className="with-icon">
                  <MapPin className="field-icon" size={18} strokeWidth={2.2} style={{ color }} aria-hidden="true" />
                  <PlaceAutocomplete
                    id={`origin-${p.key}`}
                    value={p.origin}
                    hasError={!!err?.origin}
                    onChange={(hit) => props.onChangeParticipant(p.key, { origin: hit })}
                  />
                </div>
                {err?.origin && <p className="field-error">{err.origin}</p>}
              </div>
            </div>
          )
        })}

        <button type="button" className="add-card" onClick={props.onAdd} disabled={count >= MAX_PARTICIPANTS}>
          <Plus size={18} strokeWidth={2.4} aria-hidden="true" />
          {count >= MAX_PARTICIPANTS ? `최대 ${MAX_PARTICIPANTS}명까지 추가할 수 있어요` : '참여자 추가'}
        </button>
      </section>

      <section aria-label="모임 조건">
        <div className="section-title">
          <h2>모임 목적</h2>
        </div>
        <div className="purpose-chips" role="radiogroup" aria-label="모임 목적">
          {PURPOSE_OPTIONS.map((o) => {
            const Icon = PURPOSE_ICONS[o.value]
            return (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={purpose === o.value}
                className={`purpose-chip${purpose === o.value ? ' active' : ''}`}
                onClick={() => props.onPurpose(o.value)}
              >
                <Icon size={26} strokeWidth={2} aria-hidden="true" />
                <span>{o.label}</span>
              </button>
            )
          })}
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
        <StateMessage Icon={SearchX} tone="error" title="앗, 추천을 가져오지 못했어요" role="alert">
          {submitError}
        </StateMessage>
      )}

      <div className="submit-bar">
        {missing && <p className="submit-hint">{missing}</p>}
        <button type="submit" className="btn primary block" disabled={!ready}>
          추천 받기
        </button>
      </div>
    </form>
  )
}
