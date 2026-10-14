# config

점수 계산 가중치와 추천 파라미터를 둔다. 코드에 가중치를 하드코딩하지 않는다.

- `region.yaml`: RegionScore 가중치(평균·최대·표준편차), 후보 역 수 K, 상위 지역 수
- `travel.yaml`: mock 이동시간 추정 파라미터, ODsay 타임아웃
- `place_weights.yaml` (예정): PlaceScore 가중치 (접근성, 평점, 리뷰 수, 목적 적합성, 연령대)
