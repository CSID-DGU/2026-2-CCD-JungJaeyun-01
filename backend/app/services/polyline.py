"""Google 인코딩 폴리라인 디코더 (https://developers.google.com/maps/documentation/utilities/polylinealgorithm)."""


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """인코딩된 문자열 → [(lat, lng), ...]. 정밀도는 소수점 5자리."""
    points: list[tuple[float, float]] = []
    index = lat = lng = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):  # 위도 변화량, 경도 변화량
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        points.append((lat / 1e5, lng / 1e5))
    return points
