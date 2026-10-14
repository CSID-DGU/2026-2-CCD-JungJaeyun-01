import json
from pathlib import Path

import pytest

from app.config import load_estimate_params
from app.geo import Coord
from app.route_model import SUBWAY, WALK
from app.stations import Station, load_stations
from app.subway import EstimateParams, SubwayNetwork, TravelEstimator, load_network

FIXTURES = Path(__file__).parent / "fixtures"
PARAMS = EstimateParams(walk_speed_kmh=4.5, detour_factor=1.3, boarding_wait_minutes=3.0, egress_minutes=1.0,
                        nearest_station_k=2, fallback_transit_speed_kmh=30, fallback_access_minutes=10)


def tiny_network(extra_edges=(), transfer_minutes=4.0):
    """L1: 가 - 나 - 다,  L2: 나 - 라 - 마  (나에서 환승)."""
    def st(line, name, lat, lng):
        return {"id": f"{line}|{name}", "line": line, "name": name, "lat": lat, "lng": lng}

    data = {
        "lines": {"L1": {"color": "#111111"}, "L2": {"color": "#222222"}},
        "stations": [st("L1", "가", 37.50, 127.00), st("L1", "나", 37.50, 127.02), st("L1", "다", 37.50, 127.04),
                     st("L2", "나", 37.50, 127.02), st("L2", "라", 37.52, 127.02), st("L2", "마", 37.54, 127.02)],
        "edges": [{"a": "L1|가", "b": "L1|나", "minutes": 3}, {"a": "L1|나", "b": "L1|다", "minutes": 3},
                  {"a": "L2|나", "b": "L2|라", "minutes": 2}, {"a": "L2|라", "b": "L2|마", "minutes": 2}, *extra_edges],
        "transfers": [{"a": "L1|나", "b": "L2|나", "minutes": transfer_minutes}],
    }
    return SubwayNetwork.from_dict(data)


def dest(name: str, lat: float, lng: float) -> Station:
    return Station(id=name, name=f"{name}역", coord=Coord(lat, lng))


class TestShortestTime:
    def test_includes_ride_and_transfer_time(self):
        dist, _ = tiny_network().shortest({"L1|가": 0.0})
        assert dist["L1|나"] == 3 and dist["L1|다"] == 6
        assert dist["L2|마"] == 3 + 4 + 2 + 2  # 가→나 3 + 환승 4 + 나→라 2 + 라→마 2

    def test_takes_the_faster_edge_when_there_are_alternatives(self):
        net = tiny_network(extra_edges=[{"a": "L1|가", "b": "L1|다", "minutes": 4}])
        dist, _ = net.shortest({"L1|가": 0.0})
        assert dist["L1|다"] == 4  # 직행 간선이 3+3보다 빠르다

    def test_transfer_cost_changes_the_best_route(self):
        slow = tiny_network(transfer_minutes=50.0)
        dist, _ = slow.shortest({"L1|가": 0.0})
        assert dist["L2|마"] == 3 + 50 + 4

    def test_multiple_sources_start_from_the_cheaper_one(self):
        dist, _ = tiny_network().shortest({"L1|가": 10.0, "L2|라": 1.0})
        assert dist["L2|마"] == 3

    def test_unreachable_nodes_are_absent(self):
        data = {"lines": {"L1": {"color": "#1"}}, "transfers": [], "edges": [],
                "stations": [{"id": "L1|x", "line": "L1", "name": "x", "lat": 37.5, "lng": 127.0},
                             {"id": "L1|y", "line": "L1", "name": "y", "lat": 37.6, "lng": 127.0}]}
        dist, _ = SubwayNetwork.from_dict(data).shortest({"L1|x": 0.0})
        assert "L1|y" not in dist


class TestEstimator:
    def test_estimate_adds_walk_wait_ride_and_egress(self):
        est = TravelEstimator(tiny_network(), PARAMS)
        origin = Coord(37.50, 127.0 + 0.0005)  # '가'역에서 약 45m
        target = dest("마", 37.54, 127.02)
        minutes = est.estimate(origin, [target])["마"]
        walk = 45 * 1.3 / (4.5 * 1000 / 60)
        assert minutes == pytest.approx(walk + 3.0 + 11 + 1.0, abs=0.3)

    def test_nearest_k_stations_are_all_considered(self):
        # 출발지는 '나'(환승역)가 가장 가깝다 → 가→나 환승 없이 L2로 바로 간다
        est = TravelEstimator(tiny_network(), PARAMS)
        origin = Coord(37.50, 127.02)
        assert est.estimate(origin, [dest("마", 37.54, 127.02)])["마"] == pytest.approx(0.0 + 3.0 + 4 + 1.0, abs=0.2)

    def test_station_missing_from_the_graph_uses_the_distance_fallback(self):
        est = TravelEstimator(tiny_network(), PARAMS)
        far = dest("없는곳", 37.60, 127.10)
        assert est.estimate(Coord(37.50, 127.0), [far])["없는곳"] > PARAMS.fallback_access_minutes

    def test_all_candidates_are_estimated_in_one_call(self):
        est = TravelEstimator(tiny_network(), PARAMS)
        result = est.estimate(Coord(37.50, 127.0), [dest("다", 37.5, 127.04), dest("마", 37.54, 127.02)])
        assert set(result) == {"다", "마"} and result["다"] < result["마"]

    def test_estimate_route_has_walk_ride_transfer_ride_walk_with_line_colors(self):
        est = TravelEstimator(tiny_network(), PARAMS)
        route = est.estimate_route(Coord(37.50, 127.0005), dest("마", 37.54, 127.02))
        assert route.source == "estimate" and route.transfers == 1
        assert [s.mode for s in route.segments] == [WALK, SUBWAY, WALK, SUBWAY, WALK]
        subway = [s for s in route.segments if s.mode == SUBWAY]
        assert [(s.line_name, s.line_color) for s in subway] == [("L1", "#111111"), ("L2", "#222222")]
        assert all(len(s.path) >= 2 for s in route.segments)

    def test_estimate_route_is_none_when_destination_not_in_graph(self):
        assert TravelEstimator(tiny_network(), PARAMS).estimate_route(Coord(37.5, 127.0), dest("없는곳", 37.6, 127.1)) is None


class TestRealNetwork:
    def test_every_candidate_station_exists_in_the_network(self):
        net = load_network()
        missing = [s.name for s in load_stations() if not net.has_station(s.name.removesuffix("역"))]
        assert missing == []

    def test_network_is_a_single_connected_component(self):
        net = load_network()
        start = next(iter(net.nodes))
        dist, _ = net.shortest({start: 0.0})
        assert len(dist) == len(net.nodes)

    @pytest.mark.parametrize("fixture, tolerance", [
        ("google_route_hapjeong_euljiro3ga.json", 4),    # 2호선 직결
        ("google_route_seouldae_anguk.json", 7),         # 2호선 → 3호선 환승
    ])
    def test_estimates_are_close_to_recorded_google_durations(self, fixture, tolerance):
        data = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
        google_minutes = int(data["response"]["routes"][0]["duration"].rstrip("s")) / 60
        stations = {s.name: s for s in load_stations()}
        origin_station, dest_station = stations[data["origin"]], stations[data["destination"]]
        est = TravelEstimator(load_network(), load_estimate_params())
        minutes = est.estimate(origin_station.coord, [dest_station])[dest_station.id]
        assert abs(minutes - google_minutes) <= tolerance

    def test_line_two_is_roughly_a_loop_of_realistic_length(self):
        est = TravelEstimator(load_network(), load_estimate_params())
        stations = {s.name: s for s in load_stations()}
        gangnam_to_hongdae = est.estimate(stations["강남역"].coord, [stations["홍대입구역"]])[stations["홍대입구역"].id]
        assert 25 <= gangnam_to_hongdae <= 45
