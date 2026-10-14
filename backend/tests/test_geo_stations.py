import pytest

from app.geo import Coord, centroid, haversine_km
from app.stations import Station, load_stations, nearest_stations


def station(id_: str, lat: float, lng: float) -> Station:
    return Station(id=id_, name=f"{id_}역", coord=Coord(lat, lng))


class TestGeo:
    def test_haversine_known_distance(self):
        # 강남역 ↔ 홍대입구역 직선거리 약 12km
        gangnam, hongdae = Coord(37.498086, 127.028001), Coord(37.556871, 126.923779)
        assert haversine_km(gangnam, hongdae) == pytest.approx(11.0, abs=1.5)

    def test_centroid(self):
        c = centroid([Coord(37.0, 127.0), Coord(38.0, 128.0)])
        assert (c.lat, c.lng) == (37.5, 127.5)

    def test_centroid_empty(self):
        with pytest.raises(ValueError):
            centroid([])


class TestNearestStations:
    def test_returns_k_closest_in_order(self):
        stations = [station("far", 37.9, 127.0), station("near", 37.5, 127.0), station("mid", 37.6, 127.0)]
        result = nearest_stations(stations, Coord(37.5, 127.0), 2)
        assert [s.id for s in result] == ["near", "mid"]

    def test_k_larger_than_stations(self):
        assert len(nearest_stations([station("a", 37.5, 127.0)], Coord(37.5, 127.0), 12)) == 1

    def test_invalid_k(self):
        with pytest.raises(ValueError):
            nearest_stations([], Coord(0, 0), 0)

    def test_real_data_loads(self):
        stations = load_stations()
        assert len(stations) >= 55
        assert all(33 < s.coord.lat < 39 and 124 < s.coord.lng < 132 for s in stations)
        assert len({s.id for s in stations}) == len(stations)
