import httpx
import pytest
from superagent.config import PlannerConfig
from superagent.models import TransitionPlan
from superagent.planner import OpenAIPlanner, PlannerError


def test_provider_stops_reading_oversized_stream_and_closes_it():
    class OversizedStream(httpx.SyncByteStream):
        consumed = 0
        closed = False

        def __iter__(self):
            for _ in range(100):
                self.consumed += 1024
                yield b'x' * 1024

        def close(self):
            self.closed = True

    stream = OversizedStream()
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream))) as client:
        planner = OpenAIPlanner(PlannerConfig(max_response_bytes=1024),
                                api_key='fixture', client=client)
        with pytest.raises(PlannerError):
            planner._request({}, TransitionPlan)
    assert stream.consumed <= 2048
    assert stream.closed


def test_provider_rejects_compression_before_decoding():
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200,headers={'Content-Encoding':'gzip'},stream=httpx.ByteStream(b'invalid gzip')))) as client:
        planner=OpenAIPlanner(PlannerConfig(),api_key='fixture',client=client)
        with pytest.raises(PlannerError):
            planner._request({},TransitionPlan)


def test_provider_enforces_elapsed_deadline_between_chunks(monkeypatch):
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'x' * 1024
    times=iter([0,2])
    monkeypatch.setattr('superagent.planner.monotonic',lambda: next(times))
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200,stream=SlowStream()))) as client:
        planner=OpenAIPlanner(PlannerConfig(timeout_seconds=1,max_response_bytes=1024),
                              api_key='fixture',client=client)
        with pytest.raises(PlannerError,match='time limit'):
            planner._request({},TransitionPlan)
