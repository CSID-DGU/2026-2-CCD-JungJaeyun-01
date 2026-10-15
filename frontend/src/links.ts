import type { Place } from './types'

/**
 * "카카오맵에서 보기" 주소.
 * 카카오 장소 id(숫자)가 있으면 상세 페이지, 없으면(예: 개발용 가짜 데이터의 mock-… id) 장소명 검색으로 연결한다.
 * 가짜 id로 place.map.kakao.com/{id}를 열면 존재하지 않는 페이지라서 "이동이 안 되는" 것처럼 보였다.
 */
export function kakaoPlaceUrl(place: Pick<Place, 'id' | 'name'>): string {
  return /^\d+$/.test(place.id)
    ? `https://place.map.kakao.com/${place.id}`
    : `https://map.kakao.com/link/search/${encodeURIComponent(place.name)}`
}
