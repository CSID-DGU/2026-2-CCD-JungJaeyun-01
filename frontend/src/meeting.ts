// 약속 시간 입력(datetime-local)과 서울 시각 다루기. 모든 시각은 서울(KST) 기준이다.
const SEOUL = 'Asia/Seoul'
const pad = (n: number) => String(n).padStart(2, '0')

/** 서울의 지금을 'YYYY-MM-DD HH:mm' 부분으로 나눈다. */
function seoulParts(now: Date) {
  const [date, time] = now.toLocaleString('sv-SE', { timeZone: SEOUL }).split(' ')
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = time.split(':').map(Number)
  return { y, m, d, hh, mm }
}

const format = (y: number, m: number, d: number, hh: number, mm: number) => `${y}-${pad(m)}-${pad(d)}T${pad(hh)}:${pad(mm)}`

/** 기본 약속 시간: 다음 토요일 오후 6시 (오늘이 토요일이어도 다음 주). 'YYYY-MM-DDTHH:mm' */
export function defaultMeetingTime(now = new Date()): string {
  const { y, m, d } = seoulParts(now)
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay() // 0=일 ... 6=토
  const days = (6 - dow + 7) % 7 || 7
  const target = new Date(Date.UTC(y, m - 1, d + days))
  return format(target.getUTCFullYear(), target.getUTCMonth() + 1, target.getUTCDate(), 18, 0)
}

/** 입력창의 min 값: 서울의 지금 */
export function seoulNowInput(now = new Date()): string {
  const { y, m, d, hh, mm } = seoulParts(now)
  return format(y, m, d, hh, mm)
}

/** 입력값(서울 시각)을 API로 보낼 ISO 문자열로 */
export const toMeetingIso = (value: string) => `${value}:00+09:00`

/** 약속 시간이 지금부터 30분 이상 뒤인지 (백엔드도 같은 기준으로 검증한다) */
export function isMeetingFarEnough(value: string, now = new Date()): boolean {
  return new Date(toMeetingIso(value)).getTime() >= now.getTime() + 30 * 60_000
}

const timeFormat = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: SEOUL })
const dateFormat = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short', timeZone: SEOUL })

/** ISO 시각 → "18:22" (서울) */
export const fmtClock = (iso: string | null | undefined): string => (iso ? timeFormat.format(new Date(iso)) : '--:--')

/** ISO 시각 → "10. 17. (토)" 같은 날짜 */
export const fmtDay = (iso: string): string => dateFormat.format(new Date(iso))

/** 두 ISO 시각 사이의 분 (반올림) */
export const minutesBetween = (from: string, to: string): number =>
  Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60_000)
