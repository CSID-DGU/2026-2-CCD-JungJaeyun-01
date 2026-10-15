import type { Place } from './types'

export type PlaceKind = 'meal' | 'cafe' | 'drink'

/** 카카오 카테고리 문자열("음식점 > 한식 > 육류,고기", "카페 > 커피전문점")로 장소 종류를 가른다. */
export function placeKind(place: Pick<Place, 'category'>): PlaceKind {
  const c = place.category
  if (/카페|커피|디저트|베이커리/.test(c)) return 'cafe'
  if (/술집|주점|호프|바\(BAR\)|이자카야|포장마차|요리주점/.test(c)) return 'drink'
  return 'meal'
}
