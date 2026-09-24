import io
import unittest
from urllib.error import HTTPError

from tmdb import TMDBClient, TMDBError, TokenBucketRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TMDBRateLimitTest(unittest.TestCase):
    def test_token_bucket_spaces_requests_after_its_burst(self):
        clock = FakeClock()
        limiter = TokenBucketRateLimiter(
            requests_per_second=4,
            burst_size=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

        self.assertEqual(clock.sleeps, [0.25])

    def test_client_acquires_a_token_before_each_request(self):
        class CountingLimiter:
            def __init__(self):
                self.calls = 0

            def acquire(self):
                self.calls += 1

        limiter = CountingLimiter()
        client = TMDBClient(
            "test-token",
            transport=lambda _request, timeout: io.BytesIO(b"{}"),
            rate_limiter=limiter,
        )

        client.popular_tv()

        self.assertEqual(limiter.calls, 1)

    def test_http_error_exposes_status_code(self):
        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        client = TMDBClient("test-token", transport=missing)
        with self.assertRaises(TMDBError) as raised:
            client.movie_credits(1368337)
        self.assertEqual(str(raised.exception), "TMDB returned HTTP 404")
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
